"use client";

import { useState } from "react";
import AudioRecorder from "@/components/AudioRecorder";
import Dashboard from "@/components/Dashboard";

export default function Home() {
  const [refreshSignal, setRefreshSignal] = useState(0);

  return (
    <main className="min-h-screen bg-gradient-to-br from-slate-50 to-indigo-50 p-4 md:p-8">
      <div className="max-w-[1400px] mx-auto">
        {/* Header */}
        <div className="mb-6">
          <h1 className="text-3xl md:text-4xl font-bold text-gray-900">
            Rizq-Rescue
          </h1>
          <p className="text-gray-500 mt-1">
            AI-Powered Food Rescue &mdash; Voice Agent Demo
          </p>
        </div>

        {/* Split layout: 60% recorder / 40% dashboard */}
        <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
          {/* Voice Agent (left, 60%) */}
          <div className="lg:col-span-3">
            <AudioRecorder
              onDonationUpdate={() =>
                setRefreshSignal((prev) => prev + 1)
              }
            />
          </div>

          {/* Dashboard (right, 40%) */}
          <div className="lg:col-span-2">
            <Dashboard refreshSignal={refreshSignal} />
          </div>
        </div>
      </div>
    </main>
  );
}
