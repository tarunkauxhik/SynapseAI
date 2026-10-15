"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { cancelResearch, cn, getTaskStatus, HttpError, TaskStatusResponse } from "@/lib/api";
import { ProgressTracker } from "@/components/ProgressTracker";
import { ReportViewer } from "@/components/ReportViewer";
import { SiteHeader, pillClass } from "@/components/SiteHeader";
import { AlertCircle, ChevronDown, Loader2, XCircle } from "lucide-react";

const primaryButton = "inline-flex items-center justify-center px-5 py-2.5 bg-white text-black hover:bg-gray-200 rounded-full text-sm font-medium transition-colors";

export default function ResearchPage() {
    const params = useParams();
    const taskId = params?.taskId as string;

    const [status, setStatus] = useState<TaskStatusResponse | null>(null);
    const [notFound, setNotFound] = useState(false);
    const [failedPolls, setFailedPolls] = useState(0); // consecutive, e.g. backend waking up or down
    const [cancelling, setCancelling] = useState(false);

    // Poll for stage, logs and report; stop once the task is done or doesn't exist
    useEffect(() => {
        if (!taskId) return;
        const poll = async () => {
            try {
                const data = await getTaskStatus(taskId);
                setStatus(data);
                setFailedPolls(0);
                if (data.status === "completed" || data.status === "failed") clearInterval(interval);
            } catch (e) {
                if (e instanceof HttpError && e.status === 404) {
                    setNotFound(true);
                    clearInterval(interval);
                } else {
                    setFailedPolls(n => n + 1);
                }
            }
        };
        const interval = setInterval(poll, 3000);
        poll();
        return () => clearInterval(interval);
    }, [taskId]);

    if (!taskId) return null;

    const isDone = status?.status === "completed";
    const isFailed = status?.status === "failed";
    const isRunning = !!status && !isDone && !isFailed;
    const logs = status?.logs ?? [];
    const lastLog = logs[logs.length - 1]?.message ?? "";
    const wasCancelled = isFailed && /cancelled/i.test(lastLog);

    const handleCancel = async () => {
        if (!window.confirm("Cancel this research task?")) return;
        setCancelling(true);
        try {
            await cancelResearch(taskId);
            setStatus(await getTaskStatus(taskId));
        } catch {
            // The next poll shows the real state
        } finally {
            setCancelling(false);
        }
    };

    return (
        <main className="min-h-screen flex flex-col">
            <SiteHeader>
                <span className="font-mono text-xs text-gray-500 hidden sm:inline">Task {taskId.slice(0, 8)}</span>
                {isRunning && (
                    <button type="button" onClick={handleCancel} disabled={cancelling} className={cn(pillClass, "hover:text-rose-300 hover:border-rose-500/30")}>
                        {cancelling ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <XCircle className="h-3.5 w-3.5" />}
                        Cancel
                    </button>
                )}
                <Link href="/" className={pillClass}>New research</Link>
            </SiteHeader>

            <div className="w-full max-w-7xl mx-auto px-4 sm:px-6 pb-16 space-y-8">
                {notFound ? (
                    <div className="glass-panel rounded-2xl p-10 text-center space-y-4 max-w-xl mx-auto mt-10">
                        <h1 className="text-xl font-semibold text-white">Task not found</h1>
                        <p className="text-gray-400 text-sm">This research task doesn&apos;t exist or has been removed.</p>
                        <Link href="/" className={primaryButton}>Start new research</Link>
                    </div>
                ) : !status ? (
                    <div className="flex flex-col items-center justify-center gap-3 py-32 text-sm text-gray-500">
                        <Loader2 className="h-8 w-8 text-blue-500 animate-spin" />
                        {failedPolls >= 2 ? "Can't reach the server yet, retrying…" : "Loading task…"}
                    </div>
                ) : (
                    <>
                        {failedPolls >= 2 && (
                            <div role="status" className="flex items-center gap-2 bg-amber-500/10 border border-amber-500/20 rounded-xl p-4 text-sm text-amber-200">
                                <Loader2 className="h-4 w-4 animate-spin shrink-0" /> Connection to the server lost, retrying…
                            </div>
                        )}

                        {isFailed && (
                            <div role="alert" className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 bg-red-500/10 border border-red-500/20 rounded-xl p-4 sm:px-6">
                                <div className="flex items-start gap-3 text-sm">
                                    <AlertCircle className="h-5 w-5 text-red-400 shrink-0" />
                                    <div>
                                        <div className="font-medium text-red-200">{wasCancelled ? "Research cancelled" : "Research failed"}</div>
                                        <div className="text-red-300/80 mt-0.5">
                                            {wasCancelled
                                                ? "This task was stopped before it finished."
                                                : lastLog.startsWith("CRITICAL ERROR:")
                                                    ? lastLog.replace("CRITICAL ERROR:", "").trim()
                                                    : "The task stopped unexpectedly, for example because the server restarted."}
                                        </div>
                                    </div>
                                </div>
                                <Link href="/" className={cn(primaryButton, "shrink-0")}>Start new research</Link>
                            </div>
                        )}

                        {isDone ? (
                            // Report first; the timeline and logs stay one click away
                            <details className="group glass-panel rounded-2xl print:hidden">
                                <summary className="flex items-center justify-between gap-4 cursor-pointer list-none p-4 sm:px-6 text-sm text-gray-400 hover:text-white transition-colors">
                                    <span>Research complete · agent timeline and logs</span>
                                    <ChevronDown className="h-4 w-4 shrink-0 transition-transform group-open:rotate-180" />
                                </summary>
                                <div className="px-4 pb-4 sm:px-6 sm:pb-6">
                                    <ProgressTracker taskId={taskId} status={status} />
                                </div>
                            </details>
                        ) : (
                            <div className="print:hidden">
                                <ProgressTracker taskId={taskId} status={status} />
                            </div>
                        )}

                        {status.result && (
                            <div className={cn(!isDone && "pt-8 border-t border-white/10")}>
                                <ReportViewer report={status.result} />
                            </div>
                        )}
                    </>
                )}
            </div>
        </main>
    );
}
