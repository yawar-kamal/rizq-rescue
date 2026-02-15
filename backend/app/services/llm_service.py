"""Gemini LLM service with function calling for food rescue coordination."""

import asyncio
import json
import logging
import re
from typing import Optional

from google import genai
from google.genai import types

from app.config import get_settings

logger = logging.getLogger(__name__)

# ── System prompts per mode ──────────────────────────────────────────

RESTAURANT_PROMPT = """آپ رزق ریسکیو کے ایجنٹ ہیں۔ آپ ریستوران سے اردو میں بات کر رہے ہیں۔

آپ کا کام ہے کہ آرام سے بات کریں اور یہ معلومات حاصل کریں:
1. کیا بچا ہوا کھانا ہے؟
2. کون سا کھانا ہے؟ (بریانی، سالن، چاول، روٹی، دال، سبزی، مکس وغیرہ)
3. کتنے کلو ہے؟

اہم اصول:
- ہمیشہ اردو میں جواب دیں۔
- بات چیت عام رکھیں، رسمی نہ ہو۔ جیسے دوست سے بات کر رہے ہوں۔
- ایک وقت میں ایک سوال پوچھیں۔
- record_donation صرف تب کال کریں جب کھانے کی قسم اور کلو دونوں معلوم ہو جائیں۔
- جوابات مختصر رکھیں (1-2 جملے)۔"""

NGO_PROMPT_TEMPLATE = """آپ رزق ریسکیو ڈسپیچ کوآرڈینیٹر ہیں۔ اردو میں والنٹیئر سے بات کر رہے ہیں۔

ڈونیشن کی تفصیلات:
- donation_id: {donation_id}
- کھانا: {food_type}
- مقدار: {quantity_kg} کلو
- ذریعہ: {source_name}
- مقام: {location}

آپ کا کام:
1. سلام کریں اور اپنا تعارف کرائیں۔
2. کھانے کی تفصیلات بتائیں۔
3. پوچھیں کیا 30 منٹ میں اٹھا سکتے ہیں۔
4. جواب کے بعد assign_volunteer کال کریں۔

اہم اصول:
- ہمیشہ اردو میں جواب دیں۔
- بات چیت آرام سے رکھیں۔
- assign_volunteer صرف واضح جواب ملنے پر کال کریں۔"""


# ── Function declarations for Gemini ─────────────────────────────────

RECORD_DONATION_DECL = types.FunctionDeclaration(
    name="record_donation",
    description="Record a donation after collecting food type and quantity in kg.",
    parameters=types.Schema(
        type="OBJECT",
        properties={
            "food_type": types.Schema(
                type="STRING",
                description="Food category (biryani, curry, rice, bread, daal, sabzi, mixed)",
            ),
            "quantity_kg": types.Schema(type="NUMBER", description="Quantity in kilograms"),
        },
        required=["food_type", "quantity_kg"],
    ),
)

ASSIGN_VOLUNTEER_DECL = types.FunctionDeclaration(
    name="assign_volunteer",
    description="Assign a volunteer decision to the latest donation dispatch call.",
    parameters=types.Schema(
        type="OBJECT",
        properties={
            "donation_id": types.Schema(
                type="INTEGER",
                description="ID of donation to assign",
            ),
            "volunteer_accepts": types.Schema(
                type="BOOLEAN",
                description="Whether volunteer accepts pickup",
            ),
            "volunteer_name": types.Schema(
                type="STRING",
                description="Optional volunteer name if mentioned",
            ),
            "volunteer_phone": types.Schema(
                type="STRING",
                description="Optional volunteer phone if mentioned",
            ),
        },
        required=["donation_id", "volunteer_accepts"],
    ),
)

COORDINATION_TOOL = types.Tool(
    function_declarations=[RECORD_DONATION_DECL, ASSIGN_VOLUNTEER_DECL]
)


class GeminiLLMService:
    """Manages a Gemini chat session per WebSocket connection."""

    def __init__(self, mode: str = "restaurant"):
        settings = get_settings()
        self.client = genai.Client(api_key=settings.gemini_api_key)
        self.mode = mode
        self.ngo_target_donation = None
        if mode == "ngo":
            try:
                from app.models.database import get_latest_pending_donation

                self.ngo_target_donation = get_latest_pending_donation()
            except Exception as exc:
                logger.warning("Could not load latest pending donation: %s", exc)

        # Deterministic flow guards to prevent early confirmations/hallucinations.
        self.restaurant_stage = "greeting"
        self.restaurant_food_type: Optional[str] = None
        self.restaurant_quantity_kg: Optional[float] = None
        self.restaurant_serves_people: Optional[int] = None
        self.ngo_stage = "acceptance_check"
        self.system_prompt = self._build_system_prompt()

        # Model candidates — tries each in order, first success wins
        self.model_candidates = [
            "models/gemini-2.5-flash-preview-09-2025",
            "models/gemini-2.0-flash",
            "models/gemini-2.0-flash-lite",
            "models/gemini-1.5-flash",
        ]

        self.history: list[types.Content] = []
        self.selected_model: Optional[str] = None
        logger.info("GeminiLLMService created (mode=%s)", mode)

    def _build_system_prompt(self) -> str:
        if self.mode == "restaurant":
            return RESTAURANT_PROMPT

        donation = self.ngo_target_donation or {}
        return NGO_PROMPT_TEMPLATE.format(
            donation_id=donation.get("id", "N/A"),
            food_type=donation.get("food_type", "unknown"),
            quantity_kg=donation.get("quantity_kg", "unknown"),
            source_name=donation.get("source_name", "nearby partner restaurant"),
            location=donation.get("source_location", "location will be shared after confirmation"),
        )

    def get_opening_greeting(self) -> str:
        """Return and persist an opening greeting for a new recording turn."""
        if self.mode == "restaurant":
            greeting = (
                "السلام علیکم! میں رزق ریسکیو سے بات کر رہا ہوں۔ "
                "کیا آج آپ کے پاس کچھ بچا ہوا کھانا ہے جو ہم ضرورت مندوں تک پہنچا سکیں؟"
            )
        else:
            donation = self.ngo_target_donation
            if donation:
                greeting = (
                    f"السلام علیکم! میں رزق ریسکیو ڈسپیچ سے ہوں۔ "
                    f"ہمارے پاس {donation.get('quantity_kg', 0)} کلو {donation.get('food_type', 'کھانا')} "
                    "تیار ہے پک اپ کے لیے۔ کیا آپ اگلے 30 منٹ میں اٹھا سکتے ہیں؟"
                )
            else:
                greeting = (
                    "السلام علیکم! میں رزق ریسکیو ڈسپیچ سے ہوں۔ "
                    "ابھی کوئی پک اپ دستیاب نہیں ہے، اگلی اپ ڈیٹ کا انتظار کریں۔"
                )

        self.history.append(types.Content(role="model", parts=[types.Part(text=greeting)]))
        return greeting

    def _is_positive(self, text: str) -> bool:
        t = text.lower()
        return any(w in t for w in [
            "yes", "yeah", "yep", "sure", "ok", "okay", "of course", "why not",
            "haan", "han", "ji", "jee", "bilkul", "zaroor", "theek", "thik",
            "available", "hai", "hein", "ہاں", "جی", "بلکل", "ضرور", "ٹھیک",
        ])

    def _is_negative(self, text: str) -> bool:
        t = text.lower()
        return any(w in t for w in [
            "no", "nope", "not", "cannot", "can't", "don't",
            "nahi", "nahin", "nah", "mat", "نہیں", "نہ", "مت",
        ])

    def _normalize_food_type(self, text: str) -> Optional[str]:
        t = text.lower()
        food_map = {
            "biryani": ["biryani", "بریانی", "pulao", "پلاؤ"],
            "curry": ["curry", "karahi", "salan", "qorma", "korma", "nihari",
                       "chicken", "mutton", "gosht",
                       "چکن", "کڑاہی", "سالن", "قورمہ", "نہاری", "گوشت", "کری"],
            "rice": ["rice", "chawal", "چاول"],
            "bread": ["bread", "roti", "naan", "paratha", "chapati",
                       "روٹی", "نان", "پراٹھا", "چپاتی", "بریڈ"],
            "daal": ["daal", "dal", "lentil", "دال"],
            "sabzi": ["sabzi", "sabji", "vegetable", "سبزی", "بھنڈی", "آلو", "گوبھی"],
            "mixed": ["mixed", "mix", "مکس", "سب", "مختلف"],
        }
        for category, keywords in food_map.items():
            if any(w in t for w in keywords):
                return category
        return None

    def _extract_quantity(self, text: str) -> Optional[float]:
        t = text.lower()
        kg_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:kg|kilo|kilogram|کلو)", t)
        if kg_match:
            return float(kg_match.group(1))
        num_match = re.search(r"\b(\d+(?:\.\d+)?)\b", t)
        if num_match:
            return float(num_match.group(1))
        return None

    def _make_reply(self, text: str, fn_called=False, fn_name=None, fn_args=None) -> dict:
        return {
            "text": text,
            "function_called": fn_called,
            "function_name": fn_name,
            "function_args": fn_args,
        }

    async def _rule_based_flow(self, user_text: str) -> Optional[dict]:
        """Casual Urdu conversation guardrails. Extracts info from natural speech."""
        text = (user_text or "").strip()
        if not text:
            return None

        if self.mode == "restaurant":
            # Try to extract food type and quantity from ANY message
            food_type = self._normalize_food_type(text)
            quantity = self._extract_quantity(text)

            # Accumulate info across turns
            if food_type:
                self.restaurant_food_type = food_type
            if quantity:
                self.restaurant_quantity_kg = quantity

            # ── Stage: greeting ──────────────────────────
            if self.restaurant_stage == "greeting":
                if self._is_negative(text):
                    self.restaurant_stage = "completed"
                    return self._make_reply(
                        "کوئی بات نہیں، شکریہ آپ کا۔ اگلی بار ضرور بتائیں!"
                    )

                # User might say "haan biryani hai 10 kg" all at once
                if self.restaurant_food_type and self.restaurant_quantity_kg:
                    return await self._save_donation()

                if self.restaurant_food_type:
                    self.restaurant_stage = "quantity_check"
                    return self._make_reply(
                        f"بہت اچھا! {self.restaurant_food_type} ہے۔ اندازاً کتنے کلو ہوں گے؟"
                    )

                # Any positive or unclear → ask food type
                self.restaurant_stage = "type_check"
                return self._make_reply(
                    "بہت اچھا! بتائیں کیا کھانا ہے؟ جیسے بریانی، سالن، چاول، روٹی، دال، سبزی؟"
                )

            # ── Stage: type_check ────────────────────────
            if self.restaurant_stage == "type_check":
                if self.restaurant_food_type and self.restaurant_quantity_kg:
                    return await self._save_donation()

                if self.restaurant_food_type:
                    self.restaurant_stage = "quantity_check"
                    return self._make_reply(
                        f"ٹھیک ہے، {self.restaurant_food_type}۔ کتنے کلو ہے اندازاً؟"
                    )

                return self._make_reply(
                    "کون سا کھانا ہے؟ بریانی، سالن، چاول، روٹی، دال، سبزی، یا مکس؟"
                )

            # ── Stage: quantity_check ─────────────────────
            if self.restaurant_stage == "quantity_check":
                if self.restaurant_food_type and self.restaurant_quantity_kg:
                    return await self._save_donation()

                if self.restaurant_quantity_kg:
                    return await self._save_donation()

                return self._make_reply(
                    "اندازاً کتنے کلو ہے؟"
                )

        # ── NGO mode ─────────────────────────────────────
        if self.mode == "ngo" and self.ngo_target_donation:
            if self.ngo_stage == "acceptance_check":
                if self._is_positive(text):
                    self.ngo_stage = "completed"
                    try:
                        from app.models.database import assign_volunteer_to_donation
                        donation_id = int(self.ngo_target_donation.get("id") or 0)
                        assign_volunteer_to_donation(
                            donation_id=donation_id,
                            volunteer_name="Volunteer",
                            volunteer_phone="",
                        )
                        return self._make_reply(
                            "بہت شکریہ! پک اپ آپ کو اسائن ہو گیا ہے۔ احتیاط سے آئیں۔ جزاک اللہ!",
                            fn_called=True,
                            fn_name="assign_volunteer",
                            fn_args={"donation_id": donation_id, "volunteer_accepts": True},
                        )
                    except Exception as exc:
                        logger.error("assign_volunteer failed: %s", exc)
                        return self._make_reply(
                            "ابھی اسائن نہیں ہو سکا، لیکن شکریہ قبول کرنے کا!"
                        )

                if self._is_negative(text):
                    self.ngo_stage = "completed"
                    return self._make_reply(
                        "کوئی بات نہیں، ہم کسی اور والنٹیئر کو بھیجتے ہیں۔ شکریہ!",
                        fn_called=True,
                        fn_name="assign_volunteer",
                        fn_args={
                            "donation_id": int(self.ngo_target_donation.get("id") or 0),
                            "volunteer_accepts": False,
                        },
                    )

                return self._make_reply(
                    "کیا آپ اگلے 30 منٹ میں پک اپ کر سکتے ہیں؟"
                )

        return None

    async def _save_donation(self) -> dict:
        """Save collected food info and return confirmation in Urdu."""
        self.restaurant_stage = "completed"
        food = self.restaurant_food_type or "mixed"
        kg = self.restaurant_quantity_kg or 0

        try:
            from app.models.database import create_donation
            donation_id = create_donation(
                food_type=food,
                quantity_kg=float(kg),
                serves_people=0,
            )
            return self._make_reply(
                f"بہت شکریہ! ہم نے {kg} کلو {food} نوٹ کر لیا ہے۔ "
                "ہمارا والنٹیئر جلد آپ سے رابطہ کرے گا۔ اللہ حافظ!",
                fn_called=True,
                fn_name="record_donation",
                fn_args={
                    "food_type": food,
                    "quantity_kg": float(kg),
                    "donation_id": donation_id,
                },
            )
        except Exception as exc:
            logger.error("record_donation failed: %s", exc)
            return self._make_reply(
                "ابھی محفوظ نہیں ہو سکا، دوبارہ بتائیں کتنے کلو ہے؟"
            )

    async def _generate_with_fallback(
        self,
        contents: list[types.Content],
        config: types.GenerateContentConfig,
        preferred_model: Optional[str] = None,
    ):
        model_order = list(self.model_candidates)
        if preferred_model in model_order:
            model_order.remove(preferred_model)
            model_order.insert(0, preferred_model)

        last_error = None
        for model_name in model_order:
            try:
                response = await asyncio.to_thread(
                    self.client.models.generate_content,
                    model=model_name,
                    contents=contents,
                    config=config,
                )
                self.selected_model = model_name
                return response
            except Exception as exc:
                last_error = exc
                logger.warning("Model %s failed: %s", model_name, exc)

        raise RuntimeError(f"All Gemini models failed. Last error: {last_error}")

    async def generate_response(self, user_text: str) -> dict:
        self.history.append(types.Content(role="user", parts=[types.Part(text=user_text)]))

        # Hard guardrail path to enforce turn order and prevent early "thank you".
        guarded = await self._rule_based_flow(user_text)
        if guarded is not None:
            return guarded

        config = types.GenerateContentConfig(
            system_instruction=self.system_prompt,
            tools=[COORDINATION_TOOL],
            temperature=0.5,
            max_output_tokens=256,
        )

        try:
            response = await self._generate_with_fallback(self.history, config)
        except Exception as exc:
            logger.error("%s", exc)
            return {
                "text": "I am having trouble responding right now. Please try again.",
                "function_called": False,
                "function_name": None,
                "function_args": None,
            }

        ai_text = ""
        function_called = False
        function_name = None
        function_args = None

        for part in response.candidates[0].content.parts:
            if part.text:
                ai_text += part.text
            elif part.function_call:
                function_called = True
                function_name = part.function_call.name
                function_args = dict(part.function_call.args) if part.function_call.args else {}
                logger.info("Function call: %s(%s)", function_name, json.dumps(function_args))

        if function_called:
            self.history.append(response.candidates[0].content)
            donation_id = None

            if function_name == "record_donation":
                try:
                    from app.models.database import create_donation
                    donation_id = create_donation(
                        food_type=str(function_args.get("food_type", "mixed")),
                        quantity_kg=float(function_args.get("quantity_kg", 0)),
                        serves_people=int(function_args.get("serves_people", 0)),
                    )
                    function_result = {
                        "success": True,
                        "donation_id": donation_id,
                        "message": f"Donation #{donation_id} recorded successfully.",
                    }
                except Exception as exc:
                    logger.error("record_donation failed: %s", exc)
                    function_result = {"success": False, "error": str(exc)}

            elif function_name == "assign_volunteer":
                try:
                    donation_id = int(function_args.get("donation_id") or 0)
                    if donation_id <= 0:
                        from app.models.database import get_latest_pending_donation
                        latest = get_latest_pending_donation()
                        donation_id = int(latest["id"]) if latest else 0

                    volunteer_accepts = bool(function_args.get("volunteer_accepts", False))
                    volunteer_name = str(function_args.get("volunteer_name") or "Volunteer")
                    volunteer_phone = str(function_args.get("volunteer_phone") or "")

                    if donation_id <= 0:
                        function_result = {
                            "success": False,
                            "error": "No pending donation found to assign.",
                        }
                    elif volunteer_accepts:
                        from app.models.database import assign_volunteer_to_donation
                        assigned = assign_volunteer_to_donation(
                            donation_id=donation_id,
                            volunteer_name=volunteer_name,
                            volunteer_phone=volunteer_phone,
                        )
                        function_result = {
                            "success": assigned,
                            "donation_id": donation_id,
                            "volunteer_accepts": True,
                            "message": "Volunteer assigned." if assigned else "Assignment failed.",
                        }
                    else:
                        function_result = {
                            "success": True,
                            "donation_id": donation_id,
                            "volunteer_accepts": False,
                            "message": "Volunteer declined. Will find another volunteer.",
                        }
                except Exception as exc:
                    logger.error("assign_volunteer failed: %s", exc)
                    function_result = {"success": False, "error": str(exc)}
            else:
                function_result = {"success": False, "error": "Unknown function call"}

            self.history.append(
                types.Content(
                    role="user",
                    parts=[
                        types.Part(
                            function_response=types.FunctionResponse(
                                name=function_name,
                                response={"result": function_result},
                            )
                        )
                    ],
                )
            )

            try:
                follow_up = await self._generate_with_fallback(
                    self.history,
                    types.GenerateContentConfig(
                        system_instruction=self.system_prompt,
                        temperature=0.5,
                        max_output_tokens=256,
                    ),
                    preferred_model=self.selected_model,
                )
                if follow_up.candidates[0].content.parts:
                    ai_text = follow_up.candidates[0].content.parts[0].text or ai_text
                self.history.append(follow_up.candidates[0].content)
            except Exception as exc:
                logger.warning("Follow-up generation failed: %s", exc)
                if not ai_text:
                    ai_text = "Done. Thank you."

            if isinstance(function_args, dict) and donation_id:
                function_args["donation_id"] = donation_id
        else:
            self.history.append(response.candidates[0].content)

        logger.info(
            "Gemini [%s] -> text=%s... fn=%s",
            self.selected_model,
            ai_text[:80],
            function_called,
        )
        return {
            "text": ai_text.strip(),
            "function_called": function_called,
            "function_name": function_name,
            "function_args": function_args,
        }

    def reset(self):
        """Reset conversation history."""
        self.history = []
        logger.info("Conversation history reset")
