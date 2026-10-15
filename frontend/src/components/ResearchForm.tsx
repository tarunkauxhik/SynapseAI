"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { startResearch } from "@/lib/api";
import { AlertCircle, Loader2, Search } from "lucide-react";
import { cn } from "@/lib/api";

export function ResearchForm() {
    const router = useRouter();
    const [topic, setTopic] = useState("");
    const [isLoading, setIsLoading] = useState(false);
    const [isSlow, setIsSlow] = useState(false);
    const [error, setError] = useState<string | null>(null);

    // The free Render backend can take up to a minute to wake up; say so instead of spinning silently
    useEffect(() => {
        if (!isLoading) return;
        const timer = setTimeout(() => setIsSlow(true), 5000);
        return () => { clearTimeout(timer); setIsSlow(false); };
    }, [isLoading]);

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!topic.trim()) return;

        setIsLoading(true);
        setError(null);

        try {
            const response = await startResearch({ topic });
            router.push(`/research/${response.task_id}`);
        } catch {
            setError("Couldn't start the research. Please try again in a moment.");
            setIsLoading(false);
        }
    };

    return (
        <div className="w-full">
            <div className="relative group">
                <div className="absolute -inset-1 bg-gradient-to-r from-blue-600 to-purple-600 rounded-2xl blur opacity-25 group-hover:opacity-50 group-focus-within:opacity-50 transition duration-1000 group-hover:duration-200" />

                <div className="relative glass-panel rounded-2xl p-1 group-focus-within:ring-2 group-focus-within:ring-blue-500/50">
                    <form onSubmit={handleSubmit} className="relative flex items-center p-2">
                        <Search className="absolute left-5 sm:left-6 h-5 w-5 text-gray-400 group-focus-within:text-blue-400 transition-colors" />
                        <label htmlFor="topic" className="sr-only">Research topic</label>
                        <input
                            id="topic"
                            type="text"
                            value={topic}
                            onChange={(e) => setTopic(e.target.value)}
                            placeholder="What should I research?"
                            className="w-full min-w-0 bg-transparent border-none outline-none text-white placeholder-gray-500 focus:ring-0 pl-11 sm:pl-12 pr-2 sm:pr-4 py-4 text-base sm:text-lg"
                            disabled={isLoading}
                            autoComplete="off"
                        />
                        <button
                            type="submit"
                            disabled={isLoading || !topic.trim()}
                            className={cn(
                                "ml-2 px-5 sm:px-6 py-3 bg-white text-black font-semibold rounded-xl hover:bg-gray-200 transition-all shadow-lg flex items-center gap-2 whitespace-nowrap",
                                (isLoading || !topic.trim()) && "opacity-50 cursor-not-allowed bg-white/10 text-white hover:bg-white/10"
                            )}
                        >
                            {isLoading ? (
                                <Loader2 className="h-5 w-5 animate-spin" aria-label="Starting" />
                            ) : (
                                "Start"
                            )}
                        </button>
                    </form>
                </div>
            </div>

            {error && (
                <p role="alert" className="mt-4 flex items-center justify-center gap-2 text-sm text-rose-300">
                    <AlertCircle className="h-4 w-4 shrink-0" /> {error}
                </p>
            )}
            {isSlow && !error && (
                <p className="mt-4 text-sm text-gray-400">Waking up the server, this can take up to a minute…</p>
            )}

            {/* Helper tags */}
            <div className="mt-6 flex flex-wrap justify-center gap-2">
                {["Quantum Computing", "Future of AI", "Renewable Energy", "Space Exploration"].map((tag) => (
                    <button
                        key={tag}
                        type="button"
                        onClick={() => setTopic(tag)}
                        className="text-xs px-3 py-1.5 rounded-full border border-white/10 hover:bg-white/5 transition-colors text-gray-500 hover:text-white"
                    >
                        {tag}
                    </button>
                ))}
            </div>
        </div>
    );
}
