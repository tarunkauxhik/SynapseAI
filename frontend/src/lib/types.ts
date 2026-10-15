/* Types for the evals page (mirror app/api/eval_routes.py + evals/types.py) */

export interface GraderBreakdown {
    passed: boolean;
    score: number;
    reason: string;
    weight?: number;
}

export interface EvalResult {
    name: string;
    input: string;
    expected: string | Record<string, unknown>;
    passed: boolean;
    score: number;
    reason: string;
    latency_ms: number;
    error?: string | null;
    task_id?: string | null;
    grader_breakdown?: Record<string, GraderBreakdown>;
    tools_used?: string[];
    sources_cited?: string[];
}

export interface EvalSummary {
    total: number;
    passed: number;
    failed: number;
    errors: number;
    pass_rate: number;
    avg_score: number;
    avg_latency_ms: number;
}

export type EvalRunStatus = "running" | "completed" | "failed" | "cancelled";

export interface EvalRun {
    id: string;
    status: EvalRunStatus;
    agent_model: string;
    judge_model: string;
    dataset: string;
    total_cases: number;
    summary: Partial<EvalSummary>;
    results: EvalResult[];
    error?: string | null;
    created_at: string;
    finished_at?: string | null;
}

export interface EvalConfig {
    agent_models: string[];
    judge_model: string;
    cooldown_hours: number;
}

export interface DatasetInfo {
    name: string;
    file: string;
    count: number;
}
