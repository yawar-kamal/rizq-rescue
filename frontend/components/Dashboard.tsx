"use client";

import { useCallback, useEffect, useState } from "react";

/* ── Types ──────────────────────────────────────────────── */

interface Donation {
  id: number;
  food_type: string;
  quantity_kg: number;
  serves_people: number;
  status: string;
  created_at: string;
  volunteer_name?: string;
  volunteer_phone?: string;
  assigned_at?: string;
}

interface Stats {
  total_donations: number;
  total_kg: number;
  donations_today: number;
}

interface DashboardProps {
  /** Bump this number to trigger a re-fetch (e.g. on donation_update WS event) */
  refreshSignal?: number;
}

/* ── Helpers ─────────────────────────────────────────────── */

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const foodEmoji: Record<string, string> = {
  biryani: "🍚",
  curry: "🍛",
  rice: "🍚",
  bread: "🍞",
  daal: "🥘",
  sabzi: "🥗",
  mixed: "🥡",
};

const statusBadge: Record<string, string> = {
  pending: "bg-yellow-100 text-yellow-800 border-yellow-300",
  assigned: "bg-blue-100 text-blue-800 border-blue-300",
  picked_up: "bg-green-100 text-green-800 border-green-300",
  delivered: "bg-emerald-100 text-emerald-800 border-emerald-300",
  cancelled: "bg-red-100 text-red-800 border-red-300",
};

function timeAgo(isoString: string): string {
  try {
    const date = new Date(isoString);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const mins = Math.floor(diffMs / 60000);
    if (mins < 1) return "just now";
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    return date.toLocaleDateString();
  } catch {
    return isoString;
  }
}

/* ── Component ──────────────────────────────────────────── */

export default function Dashboard({ refreshSignal }: DashboardProps) {
  const [donations, setDonations] = useState<Donation[]>([]);
  const [stats, setStats] = useState<Stats>({
    total_donations: 0,
    total_kg: 0,
    donations_today: 0,
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const fetchData = useCallback(async () => {
    try {
      const [donRes, statsRes] = await Promise.all([
        fetch(`${API_BASE}/api/donations`),
        fetch(`${API_BASE}/api/stats`),
      ]);

      if (!donRes.ok || !statsRes.ok) {
        throw new Error("Failed to fetch dashboard data");
      }

      const donData = await donRes.json();
      const statsData = await statsRes.json();

      setDonations(donData.donations || []);
      setStats(statsData);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Network error");
    } finally {
      setLoading(false);
    }
  }, []);

  // Fetch on mount
  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Re-fetch when refreshSignal changes (donation_update from WS)
  useEffect(() => {
    if (refreshSignal && refreshSignal > 0) {
      fetchData();
    }
  }, [refreshSignal, fetchData]);

  // Also poll every 15s as backup
  useEffect(() => {
    const interval = setInterval(fetchData, 15000);
    return () => clearInterval(interval);
  }, [fetchData]);

  /* ── Render ──────────────────────────────────────────── */

  return (
    <div className="space-y-6">
      {/* ── Stats Cards ──────────────────────────────────── */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {/* Total Donations */}
        <div className="bg-white rounded-xl shadow-lg p-5 border-l-4 border-indigo-500">
          <p className="text-sm font-medium text-gray-500 uppercase tracking-wide">
            Total Donations
          </p>
          <p className="mt-2 text-3xl font-bold text-gray-900">
            {stats.total_donations}
          </p>
        </div>

        {/* Total KG */}
        <div className="bg-white rounded-xl shadow-lg p-5 border-l-4 border-green-500">
          <p className="text-sm font-medium text-gray-500 uppercase tracking-wide">
            KG Rescued
          </p>
          <p className="mt-2 text-3xl font-bold text-gray-900">
            {stats.total_kg.toFixed(1)}
            <span className="text-lg font-normal text-gray-500 ml-1">kg</span>
          </p>
        </div>

        {/* Today */}
        <div className="bg-white rounded-xl shadow-lg p-5 border-l-4 border-amber-500">
          <p className="text-sm font-medium text-gray-500 uppercase tracking-wide">
            Today
          </p>
          <p className="mt-2 text-3xl font-bold text-gray-900">
            {stats.donations_today}
          </p>
        </div>
      </div>

      {/* ── Donations Table ──────────────────────────────── */}
      <div className="bg-white rounded-xl shadow-lg overflow-hidden">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <h2 className="text-lg font-semibold text-gray-900">
            Recent Donations
          </h2>
          <button
            onClick={fetchData}
            className="text-xs px-3 py-1.5 rounded-lg bg-gray-100 text-gray-600 hover:bg-gray-200 transition-colors cursor-pointer"
          >
            Refresh
          </button>
        </div>

        {loading ? (
          <div className="p-10 text-center text-gray-400">
            <div className="inline-block w-6 h-6 border-2 border-gray-300 border-t-indigo-500 rounded-full animate-spin" />
            <p className="mt-2 text-sm">Loading donations...</p>
          </div>
        ) : error ? (
          <div className="p-10 text-center">
            <p className="text-red-500 text-sm">{error}</p>
            <button
              onClick={fetchData}
              className="mt-2 text-xs text-indigo-600 hover:underline cursor-pointer"
            >
              Retry
            </button>
          </div>
        ) : donations.length === 0 ? (
          <div className="p-10 text-center text-gray-400">
            <p className="text-4xl mb-2">📭</p>
            <p className="text-sm">No donations yet.</p>
            <p className="text-xs mt-1">
              Start a voice conversation to record your first donation!
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  <th className="px-6 py-3">Food</th>
                  <th className="px-6 py-3">Qty</th>
                  <th className="px-6 py-3">Status</th>
                  <th className="px-6 py-3">Time</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {donations.map((d) => (
                  <tr
                    key={d.id}
                    className="hover:bg-gray-50 transition-colors"
                  >
                    <td className="px-6 py-3 whitespace-nowrap">
                      <span className="mr-2">
                        {foodEmoji[d.food_type] || "📦"}
                      </span>
                      <span className="font-medium text-gray-900 capitalize">
                        {d.food_type}
                      </span>
                    </td>
                    <td className="px-6 py-3 whitespace-nowrap text-gray-700">
                      {d.quantity_kg} kg
                    </td>
                    <td className="px-6 py-3 whitespace-nowrap">
                      <span
                        className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium border ${
                          statusBadge[d.status] ||
                          "bg-gray-100 text-gray-800 border-gray-300"
                        }`}
                      >
                        {d.status}
                      </span>
                    </td>
                    <td className="px-6 py-3 whitespace-nowrap text-gray-500">
                      {timeAgo(d.created_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
