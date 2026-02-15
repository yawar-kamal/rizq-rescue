"use client";

import { useState } from "react";

interface ApiResult {
  service: string;
  status: string;
  message?: string;
  response?: string;
  error?: string;
  voice_count?: number;
  sample_voice?: string;
}

interface TestResults {
  overall_status: string;
  results: {
    soniox: ApiResult;
    gemini: ApiResult;
    elevenlabs: ApiResult;
  };
}

export default function ApiTestPanel() {
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<TestResults | null>(null);
  const [error, setError] = useState<string | null>(null);

  const API_URL =
    process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

  const runTests = async () => {
    setLoading(true);
    setError(null);
    setResults(null);

    try {
      const response = await fetch(`${API_URL}/test/apis`);
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }
      const data: TestResults = await response.json();
      setResults(data);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to connect to backend"
      );
    } finally {
      setLoading(false);
    }
  };

  const getStatusIcon = (status: string) => {
    if (status === "success" || status === "ready") return "✅";
    return "❌";
  };

  const getStatusColor = (status: string) => {
    if (status === "success" || status === "ready")
      return "bg-green-50 border-green-200 text-green-800";
    return "bg-red-50 border-red-200 text-red-800";
  };

  return (
    <div className="bg-white rounded-lg shadow-lg p-6">
      <h2 className="text-xl font-semibold text-gray-900 mb-4">
        🔌 API Integration Tests
      </h2>

      <button
        onClick={runTests}
        disabled={loading}
        className={`w-full py-3 px-6 rounded-lg font-medium text-white transition-all duration-200 ${
          loading
            ? "bg-gray-400 cursor-not-allowed"
            : "bg-indigo-600 hover:bg-indigo-700 active:bg-indigo-800 cursor-pointer"
        }`}
      >
        {loading ? (
          <span className="flex items-center justify-center gap-2">
            <svg
              className="animate-spin h-5 w-5"
              viewBox="0 0 24 24"
              fill="none"
            >
              <circle
                className="opacity-25"
                cx="12"
                cy="12"
                r="10"
                stroke="currentColor"
                strokeWidth="4"
              />
              <path
                className="opacity-75"
                fill="currentColor"
                d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
              />
            </svg>
            Running API Tests...
          </span>
        ) : (
          "🧪 Run API Tests"
        )}
      </button>

      {/* Connection Error */}
      {error && (
        <div className="mt-4 p-4 bg-red-50 border border-red-200 rounded-lg">
          <p className="text-red-800 font-medium">⚠️ Connection Error</p>
          <p className="text-red-600 text-sm mt-1">{error}</p>
          <p className="text-red-500 text-xs mt-2">
            Make sure the backend is running on {API_URL}
          </p>
        </div>
      )}

      {/* Results */}
      {results && (
        <div className="mt-6 space-y-4">
          {/* Overall Status */}
          <div
            className={`p-4 rounded-lg border-2 text-center font-bold text-lg ${
              results.overall_status === "success"
                ? "bg-green-50 border-green-400 text-green-800"
                : "bg-red-50 border-red-400 text-red-800"
            }`}
          >
            {results.overall_status === "success"
              ? "✅ ALL TESTS PASSED"
              : "❌ SOME TESTS FAILED"}
          </div>

          {/* Individual Results */}
          {Object.entries(results.results).map(([key, result]) => (
            <div
              key={key}
              className={`p-4 rounded-lg border ${getStatusColor(
                result.status
              )}`}
            >
              <div className="flex items-center justify-between">
                <span className="font-semibold capitalize">
                  {getStatusIcon(result.status)} {result.service}
                </span>
                <span className="text-sm font-mono uppercase">
                  {result.status}
                </span>
              </div>

              {/* Success details */}
              {result.message && (
                <p className="text-sm mt-2 opacity-80">{result.message}</p>
              )}
              {result.response && (
                <p className="text-sm mt-1 opacity-80">
                  Response: &quot;{result.response}&quot;
                </p>
              )}
              {result.voice_count !== undefined && (
                <p className="text-sm mt-1 opacity-80">
                  Voices available: {result.voice_count} (sample:{" "}
                  {result.sample_voice})
                </p>
              )}

              {/* Error details */}
              {result.error && (
                <p className="text-sm mt-2 text-red-600 font-mono break-all">
                  Error: {result.error}
                </p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

