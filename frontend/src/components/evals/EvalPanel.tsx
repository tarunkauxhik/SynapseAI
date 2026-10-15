'use client';

import React, { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import type { DatasetInfo, EvalConfig, EvalResult, EvalRun } from '@/lib/types';
import { SiteHeader, pillClass } from '@/components/SiteHeader';
import { cn } from '@/lib/api';
import { AlertCircle, ArrowUpRight, CheckCircle2, ChevronDown, ChevronUp, KeyRound, Link2, Loader2, Play, Square, Wrench, XCircle, Zap } from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const KEY_STORAGE = 'synapse-eval-key';

// sessionStorage can throw (private mode, blocked storage): treat that as "no key saved"
function loadKey(): string {
    try { return sessionStorage.getItem(KEY_STORAGE) || ''; } catch { return ''; }
}
function saveKey(key: string) {
    try { if (key) sessionStorage.setItem(KEY_STORAGE, key); else sessionStorage.removeItem(KEY_STORAGE); } catch { /* ignore */ }
}

async function errorDetail(res: Response): Promise<string> {
    try { return (await res.json()).detail || `Request failed (${res.status})`; } catch { return `Request failed (${res.status})`; }
}

function ProgressBar({ value, total, label }: { value: number; total: number; label: string }) {
    const percentage = total > 0 ? (value / total) * 100 : 0;
    return (
        <div className="w-full">
            <div className="flex justify-between text-sm mb-2">
                <span className="font-medium text-gray-300">{label}</span>
                <span className="text-gray-400 tabular-nums">
                    {percentage.toFixed(0)}% <span className="text-gray-500">({value}/{total})</span>
                </span>
            </div>
            <div className="w-full h-2 bg-white/5 rounded-full overflow-hidden border border-white/5">
                <div
                    className="h-full bg-gradient-to-r from-emerald-500 to-teal-400 transition-all duration-500 ease-out"
                    style={{ width: `${percentage}%` }}
                />
            </div>
        </div>
    );
}

function ScoreIndicator({ score }: { score: number }) {
    const cls = score >= 0.8 ? 'text-emerald-400 border-emerald-500/30 bg-emerald-500/10'
        : score >= 0.5 ? 'text-amber-400 border-amber-500/30 bg-amber-500/10'
            : 'text-rose-400 border-rose-500/30 bg-rose-500/10';
    return (
        <span className={`px-2.5 py-0.5 rounded border font-mono text-sm font-semibold tabular-nums ${cls}`}>
            {score.toFixed(2)}
        </span>
    );
}

const STATUS_STYLES: Record<string, string> = {
    running: 'bg-blue-500/10 text-blue-300 border-blue-500/20',
    completed: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/20',
    cancelled: 'bg-white/5 text-gray-400 border-white/10',
    failed: 'bg-rose-500/10 text-rose-300 border-rose-500/20',
};

function StatusBadge({ run }: { run: EvalRun }) {
    return (
        <span className={cn('inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium border capitalize', STATUS_STYLES[run.status])}>
            {run.status === 'running' && <Loader2 className="w-3 h-3 animate-spin" />}
            {run.status === 'running' ? `Running ${run.results.length}/${run.total_cases}` : run.status}
        </span>
    );
}

function EvalResultCard({ result }: { result: EvalResult }) {
    const [isExpanded, setIsExpanded] = useState(false);
    const hasBreakdown = result.grader_breakdown && Object.keys(result.grader_breakdown).length > 0;
    const expected = typeof result.expected === 'string' ? result.expected : JSON.stringify(result.expected, null, 2);

    return (
        <div className={cn('border rounded-xl overflow-hidden transition-colors duration-300',
            isExpanded ? 'bg-white/10 border-white/20' : 'bg-white/5 border-white/5 hover:bg-white/[0.07]')}>
            <button
                type="button"
                className="w-full flex items-center p-4 gap-3 text-left cursor-pointer"
                onClick={() => setIsExpanded(!isExpanded)}
                aria-expanded={isExpanded}
            >
                <span className={cn('flex items-center justify-center w-8 h-8 shrink-0 rounded-full border',
                    result.passed ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30' : 'bg-rose-500/20 text-rose-400 border-rose-500/30')}>
                    {result.passed ? <CheckCircle2 className="w-5 h-5" aria-label="Passed" /> : <XCircle className="w-5 h-5" aria-label="Failed" />}
                </span>
                <div className="flex-1 min-w-0">
                    <h3 className="text-gray-200 font-medium truncate text-sm">{result.name || 'Untitled Case'}</h3>
                    <div className="text-xs text-gray-500 truncate mt-0.5">{result.input}</div>
                </div>
                <ScoreIndicator score={result.score} />
                <span className="text-xs text-gray-500 font-mono w-10 text-right hidden sm:block tabular-nums">
                    {Math.round((result.latency_ms ?? 0) / 1000)}s
                </span>
                {isExpanded ? <ChevronUp className="w-4 h-4 text-gray-500 shrink-0" /> : <ChevronDown className="w-4 h-4 text-gray-500 shrink-0" />}
            </button>

            {isExpanded && (
                <div className="p-4 bg-black/20 border-t border-white/5 text-sm space-y-4">
                    <div className="space-y-1">
                        <span className="text-xs font-semibold text-purple-400 uppercase tracking-wider">Expected</span>
                        <div className="bg-black/30 p-3 rounded-lg border border-white/5 text-gray-300 text-xs whitespace-pre-wrap">{expected}</div>
                    </div>

                    {hasBreakdown && (
                        <div className="space-y-2">
                            <span className="text-xs font-semibold text-purple-400 uppercase tracking-wider flex items-center gap-2">
                                <Zap className="w-3 h-3" /> Judge Breakdown
                            </span>
                            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                                {Object.entries(result.grader_breakdown!).map(([name, b]) => (
                                    <div key={name} className={cn('p-3 rounded-lg border', b.passed ? 'bg-emerald-500/5 border-emerald-500/20' : 'bg-rose-500/5 border-rose-500/20')}>
                                        <div className="flex items-center justify-between mb-1">
                                            <span className="text-xs font-medium text-gray-300">{name.replace(/([a-z])([A-Z])/g, '$1 $2')}</span>
                                            <span className={cn('text-xs font-bold tabular-nums', b.passed ? 'text-emerald-400' : 'text-rose-400')}>
                                                {(b.score * 100).toFixed(0)}%
                                            </span>
                                        </div>
                                        <div className="text-xs text-gray-400 mt-1">{b.reason}</div>
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}

                    {result.tools_used && result.tools_used.length > 0 && (
                        <div className="space-y-1">
                            <span className="text-xs font-semibold text-cyan-400 uppercase tracking-wider flex items-center gap-2">
                                <Wrench className="w-3 h-3" /> Tools Used
                            </span>
                            <div className="flex flex-wrap gap-1.5">
                                {result.tools_used.map((tool, idx) => (
                                    <span key={idx} className="px-2 py-0.5 bg-cyan-500/10 text-cyan-300 rounded text-xs border border-cyan-500/20">{tool}</span>
                                ))}
                            </div>
                        </div>
                    )}

                    {result.sources_cited && result.sources_cited.length > 0 && (
                        <div className="space-y-1">
                            <span className="text-xs font-semibold text-orange-400 uppercase tracking-wider flex items-center gap-2">
                                <Link2 className="w-3 h-3" /> Sources Cited
                            </span>
                            <div className="bg-orange-500/5 p-2 rounded-lg border border-orange-500/10 max-h-32 overflow-auto">
                                {result.sources_cited.map((source, idx) => (
                                    <div key={idx} className="text-xs text-orange-200/80 font-mono truncate py-0.5">
                                        {source.startsWith('http') ? (
                                            <a href={source} target="_blank" rel="noopener noreferrer" className="hover:text-orange-300 underline">{source}</a>
                                        ) : source}
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}

                    <div className="space-y-1">
                        <span className="text-xs font-semibold text-amber-400 uppercase tracking-wider">Judge Reasoning</span>
                        <div className="bg-amber-500/5 p-3 rounded-lg border border-amber-500/10 text-gray-300 leading-relaxed">{result.reason}</div>
                    </div>

                    {result.error && (
                        <div className="bg-rose-500/10 p-3 rounded-lg border border-rose-500/20">
                            <span className="text-xs font-bold text-rose-400 uppercase tracking-wider block mb-1">Error</span>
                            <p className="text-rose-300 font-mono text-xs">{result.error}</p>
                        </div>
                    )}

                    {result.task_id && (
                        <Link href={`/research/${result.task_id}`} className="inline-flex items-center gap-1 text-xs font-medium text-blue-400 hover:text-blue-300">
                            Open full report <ArrowUpRight className="w-3 h-3" />
                        </Link>
                    )}
                </div>
            )}
        </div>
    );
}

function RunColumn({ model, run, onStop }: { model: string; run: EvalRun | null; onStop: (run: EvalRun) => void }) {
    const summary = run?.summary ?? {};
    const done = run?.results.length ?? 0;

    return (
        <section className="glass-panel rounded-2xl p-5 sm:p-6 space-y-5 min-w-0">
            <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                    <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">Agent model</div>
                    <span className="font-mono text-sm text-blue-200 bg-blue-500/10 px-2 py-0.5 rounded border border-blue-500/10">{model}</span>
                </div>
                {run && <StatusBadge run={run} />}
            </div>

            {!run ? (
                <div className="text-center py-10 rounded-lg border border-dashed border-white/10 text-sm text-gray-500">
                    No runs yet for this model.
                </div>
            ) : (
                <>
                    <div className="text-xs text-gray-500">
                        Started {new Date(run.created_at).toLocaleString()} · judged by <span className="font-mono text-purple-300 whitespace-nowrap">{run.judge_model}</span>
                    </div>

                    {done > 0 && (
                        <div className="grid grid-cols-3 gap-3 text-center">
                            {[
                                ['Pass rate', `${Math.round(summary.pass_rate ?? 0)}%`],
                                ['Avg score', (summary.avg_score ?? 0).toFixed(2)],
                                ['Avg time', `${Math.round((summary.avg_latency_ms ?? 0) / 1000)}s`],
                            ].map(([label, value]) => (
                                <div key={label} className="bg-black/30 rounded-lg p-3 border border-white/5">
                                    <div className="text-lg font-semibold text-white tabular-nums">{value}</div>
                                    <div className="text-[11px] text-gray-500 uppercase tracking-wider">{label}</div>
                                </div>
                            ))}
                        </div>
                    )}

                    {run.status === 'running' ? (
                        <div className="space-y-3">
                            <ProgressBar value={done} total={run.total_cases} label="Cases completed" />
                            <p className="text-xs text-gray-500">Each case runs the full research pipeline (about 1–2 min) before it is judged.</p>
                            <button
                                type="button"
                                onClick={() => onStop(run)}
                                className="px-4 py-2 bg-rose-600/20 text-rose-300 border border-rose-600/40 hover:bg-rose-600/30 rounded-lg text-sm font-medium transition-colors flex items-center gap-2"
                            >
                                <Square className="w-3.5 h-3.5 fill-current" /> Stop run
                            </button>
                        </div>
                    ) : done > 0 && (
                        <ProgressBar value={summary.passed ?? 0} total={done} label="Passed" />
                    )}

                    {run.status !== 'running' && done < run.total_cases && (
                        <p className="text-xs text-gray-500">{done} of {run.total_cases} cases finished before the run {run.status === 'cancelled' ? 'was cancelled' : 'stopped'}.</p>
                    )}
                    {run.error && <p className="text-xs text-rose-300">{run.error}</p>}

                    <div className="space-y-2">
                        {run.results.map((result, idx) => <EvalResultCard key={`${result.name}-${idx}`} result={result} />)}
                    </div>
                </>
            )}
        </section>
    );
}

export function EvalPanel() {
    const [config, setConfig] = useState<EvalConfig | null>(null);
    const [datasets, setDatasets] = useState<DatasetInfo[]>([]);
    const [runs, setRuns] = useState<Record<string, EvalRun | null>>({});
    const [model, setModel] = useState('');
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);
    const [askKey, setAskKey] = useState(false);
    const [keyInput, setKeyInput] = useState('');

    const loadRuns = useCallback(async () => {
        const res = await fetch(`${API_URL}/eval/runs/latest`);
        if (!res.ok) throw new Error(await errorDetail(res));
        setRuns((await res.json()).runs);
    }, []);

    useEffect(() => {
        (async () => {
            try {
                const [cfg, ds] = await Promise.all([
                    fetch(`${API_URL}/config`).then(r => r.json()),
                    fetch(`${API_URL}/eval/datasets`).then(r => r.json()),
                ]);
                setConfig(cfg);
                setModel(cfg.agent_models?.[0] ?? '');
                setDatasets(ds.datasets || []);
                await loadRuns();
            } catch {
                setError("Couldn't load evaluations. The backend may be waking up, try again in a minute.");
            } finally {
                setLoading(false);
            }
        })();
    }, [loadRuns]);

    // Poll only while a run is in progress
    const anyRunning = Object.values(runs).some(r => r?.status === 'running');
    useEffect(() => {
        if (!anyRunning) return;
        const interval = setInterval(() => loadRuns().catch(() => { }), 5000);
        return () => clearInterval(interval);
    }, [anyRunning, loadRuns]);

    const dataset = datasets[0];

    const startRun = async (key: string) => {
        if (!key) { setAskKey(true); return; }
        setBusy(true);
        setError(null);
        try {
            const res = await fetch(`${API_URL}/eval/run`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-Eval-Key': key },
                body: JSON.stringify({ dataset: dataset?.file, agent_model: model }),
            });
            if (res.status === 401) { saveKey(''); setAskKey(true); setError('That key was not accepted.'); return; }
            if (!res.ok) { setError(await errorDetail(res)); return; }
            saveKey(key);
            setAskKey(false);
            setKeyInput('');
            await loadRuns();
        } catch {
            setError("Couldn't reach the backend.");
        } finally {
            setBusy(false);
        }
    };

    const stopRun = async (run: EvalRun) => {
        const key = loadKey();
        if (!key) { setAskKey(true); setError('Enter the eval key to stop a run.'); return; }
        const res = await fetch(`${API_URL}/eval/runs/${run.id}`, { method: 'DELETE', headers: { 'X-Eval-Key': key } }).catch(() => null);
        if (!res?.ok) setError(res ? await errorDetail(res) : "Couldn't reach the backend.");
        setTimeout(() => loadRuns().catch(() => { }), 1000);
    };

    const runDisabled = busy || anyRunning || !config?.run_enabled || !dataset;

    return (
        <>
            <SiteHeader>
                <Link href="/" className={pillClass}>New research</Link>
            </SiteHeader>

            <div className="w-full max-w-7xl mx-auto px-4 sm:px-6 pb-16 space-y-6">
                <div className="space-y-2 pt-2">
                    <h1 className="text-3xl sm:text-4xl font-bold tracking-tight bg-clip-text text-transparent bg-gradient-to-b from-white to-white/60">
                        Evaluations
                    </h1>
                    <p className="text-gray-400 max-w-2xl">
                        Each case runs the full research pipeline and is scored by an independent judge model on content, tool use, sources and reasoning.
                    </p>
                </div>

                {/* Controls */}
                <div className="glass-panel rounded-2xl p-5 flex flex-col sm:flex-row gap-4 sm:items-end">
                    <div className="flex-1 space-y-1.5">
                        <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Dataset</span>
                        <div className="text-gray-200 py-2.5">{dataset ? `${dataset.name} · ${dataset.count} cases` : '—'}</div>
                    </div>
                    <label className="flex-1 space-y-1.5">
                        <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider block">Agent model</span>
                        <select
                            className="w-full bg-black/40 border border-white/10 text-gray-200 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-blue-500/50 outline-none cursor-pointer disabled:cursor-not-allowed"
                            value={model}
                            onChange={(e) => setModel(e.target.value)}
                            disabled={!config || anyRunning}
                        >
                            {config?.agent_models.map(m => <option key={m} value={m}>{m}</option>)}
                        </select>
                    </label>
                    <div className="flex-1 space-y-1.5">
                        <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Judge</span>
                        <div className="py-2.5">
                            <span className="font-mono text-sm text-purple-200 bg-purple-500/10 px-2 py-0.5 rounded border border-purple-500/10">{config?.judge_model ?? '—'}</span>
                        </div>
                    </div>
                    <button
                        type="button"
                        onClick={() => startRun(loadKey())}
                        disabled={runDisabled}
                        className="sm:w-auto px-6 py-2.5 bg-blue-600 hover:bg-blue-500 text-white rounded-lg font-medium transition-colors flex items-center justify-center gap-2 disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-blue-600"
                    >
                        {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4 fill-current" />} Run eval
                    </button>
                </div>

                {config && !config.run_enabled && (
                    <p className="text-sm text-gray-500">Starting new runs is disabled on this server. Showing the latest saved results.</p>
                )}

                {askKey && (
                    <form
                        className="glass-panel rounded-2xl p-5 flex flex-col sm:flex-row gap-3 sm:items-center"
                        onSubmit={(e) => { e.preventDefault(); startRun(keyInput.trim()); }}
                    >
                        <label htmlFor="eval-key" className="flex items-center gap-2 text-sm text-gray-300 shrink-0">
                            <KeyRound className="w-4 h-4 text-gray-400" /> Eval key
                        </label>
                        <input
                            id="eval-key"
                            type="password"
                            autoComplete="off"
                            value={keyInput}
                            onChange={(e) => setKeyInput(e.target.value)}
                            placeholder="Required to start or stop runs"
                            className="flex-1 bg-black/40 border border-white/10 text-gray-200 rounded-lg px-4 py-2.5 focus:ring-2 focus:ring-blue-500/50 outline-none"
                            autoFocus
                        />
                        <div className="flex gap-2">
                            <button type="submit" disabled={!keyInput.trim() || busy} className="px-5 py-2.5 bg-blue-600 hover:bg-blue-500 text-white rounded-lg font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed">
                                Start
                            </button>
                            <button type="button" onClick={() => { setAskKey(false); setError(null); }} className="px-4 py-2.5 rounded-lg text-gray-400 hover:text-white hover:bg-white/5 transition-colors">
                                Cancel
                            </button>
                        </div>
                    </form>
                )}

                {error && (
                    <div role="alert" className="flex items-start gap-2 bg-rose-500/10 border border-rose-500/20 rounded-xl p-4 text-sm text-rose-300">
                        <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" /> {error}
                    </div>
                )}

                {/* Latest run per model, side by side */}
                {loading ? (
                    <div className="flex justify-center py-20"><Loader2 className="w-6 h-6 text-blue-400 animate-spin" /></div>
                ) : config && (
                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-start">
                        {config.agent_models.map(m => (
                            <RunColumn key={m} model={m} run={runs[m] ?? null} onStop={stopRun} />
                        ))}
                    </div>
                )}
            </div>
        </>
    );
}
