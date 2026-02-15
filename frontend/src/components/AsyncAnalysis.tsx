import { useState, useEffect } from "react";
import { Upload, Loader2, CheckCircle, XCircle, Activity } from "lucide-react";
import {
  startAsyncAnalysis,
  getTaskStatus,
  cancelTask,
  TaskWebSocket,
  type TaskStatus,
} from "../api-async";
import type { Policy, Report } from "../types";

interface AsyncAnalysisProps {
  policy: Policy;
  onComplete: (report: Report) => void;
}

export default function AsyncAnalysis({ policy, onComplete }: AsyncAnalysisProps) {
  const [file, setFile] = useState<File | null>(null);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [status, setStatus] = useState<TaskStatus | null>(null);
  const [ws, setWs] = useState<TaskWebSocket | null>(null);
  const [isUploading, setIsUploading] = useState(false);

  // Clean up WebSocket on unmount
  useEffect(() => {
    return () => {
      ws?.close();
    };
  }, [ws]);

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files?.[0]) {
      setFile(e.target.files[0]);
      setTaskId(null);
      setStatus(null);
    }
  };

  const handleStartAnalysis = async () => {
    if (!file) return;

    setIsUploading(true);
    try {
      const { task_id } = await startAsyncAnalysis(file, policy);
      setTaskId(task_id);

      // Connect WebSocket for real-time updates
      const websocket = new TaskWebSocket(
        task_id,
        (update) => setStatus(update),
        (report) => {
          setStatus((prev) => ({
            ...prev!,
            state: "SUCCESS",
            ready: true,
            successful: true,
          }));
          onComplete(report);
        },
        (error) => {
          setStatus((prev) => ({
            ...prev!,
            state: "FAILURE",
            ready: true,
            successful: false,
            error,
          }));
        }
      );
      setWs(websocket);
    } catch (error) {
      console.error("Failed to start analysis:", error);
      alert("Failed to start analysis. Please try again.");
    } finally {
      setIsUploading(false);
    }
  };

  const handleCancel = async () => {
    if (!taskId) return;
    
    const success = await cancelTask(taskId);
    if (success) {
      ws?.close();
      setWs(null);
      setStatus(null);
      setTaskId(null);
    }
  };

  const getProgressColor = () => {
    if (!status) return "bg-gray-200";
    if (status.state === "SUCCESS") return "bg-green-500";
    if (status.state === "FAILURE") return "bg-red-500";
    return "bg-blue-500";
  };

  const getProgressIcon = () => {
    if (!status) return null;
    if (status.state === "SUCCESS") return <CheckCircle className="w-5 h-5 text-green-500" />;
    if (status.state === "FAILURE") return <XCircle className="w-5 h-5 text-red-500" />;
    if (status.state === "STARTED") return <Loader2 className="w-5 h-5 text-blue-500 animate-spin" />;
    return <Activity className="w-5 h-5 text-gray-500" />;
  };

  return (
    <div className="space-y-6">
      {/* File Upload */}
      {!taskId && (
        <div className="border-2 border-dashed border-gray-300 rounded-lg p-6">
          <div className="text-center">
            <Upload className="mx-auto h-12 w-12 text-gray-400" />
            <div className="mt-4">
              <label htmlFor="file-upload" className="cursor-pointer">
                <span className="mt-2 block text-sm font-medium text-gray-900">
                  {file ? file.name : "Choose a video file"}
                </span>
                <input
                  id="file-upload"
                  name="file-upload"
                  type="file"
                  accept="video/*"
                  className="sr-only"
                  onChange={handleFileSelect}
                />
              </label>
            </div>
            {file && (
              <button
                onClick={handleStartAnalysis}
                disabled={isUploading || !policy.rules.length}
                className="mt-4 px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isUploading ? (
                  <>
                    <Loader2 className="inline-block w-4 h-4 mr-2 animate-spin" />
                    Uploading...
                  </>
                ) : (
                  "Start Async Analysis"
                )}
              </button>
            )}
          </div>
        </div>
      )}

      {/* Progress Display */}
      {status && (
        <div className="bg-white rounded-lg shadow p-6">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center space-x-3">
              {getProgressIcon()}
              <div>
                <h3 className="text-lg font-medium">{status.message || status.state}</h3>
                {status.progress && (
                  <p className="text-sm text-gray-500">
                    {status.progress.stage}: {status.progress.message}
                  </p>
                )}
              </div>
            </div>
            {!status.ready && (
              <button
                onClick={handleCancel}
                className="px-3 py-1 text-sm bg-red-100 text-red-700 rounded-md hover:bg-red-200"
              >
                Cancel
              </button>
            )}
          </div>

          {/* Progress Bar */}
          {status.progress && !status.ready && (
            <div className="w-full bg-gray-200 rounded-full h-2">
              <div
                className={`h-2 rounded-full transition-all duration-500 ${getProgressColor()}`}
                style={{ width: `${status.progress.progress}%` }}
              />
            </div>
          )}

          {/* Error Display */}
          {status.error && (
            <div className="mt-4 p-3 bg-red-50 border border-red-200 rounded-md">
              <p className="text-sm text-red-700">{status.error}</p>
            </div>
          )}

          {/* Task ID */}
          <div className="mt-4 text-xs text-gray-500">
            Task ID: <code className="bg-gray-100 px-1 py-0.5 rounded">{taskId}</code>
          </div>
        </div>
      )}
    </div>
  );
}