import Link from "next/link";

// Pill style for header actions (matches the "Autonomous Research Agent" badge)
export const pillClass =
    "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-white/5 border border-white/10 text-gray-300 hover:text-white hover:bg-white/10 hover:border-white/20 transition-colors";

export function SiteHeader({ children }: { children?: React.ReactNode }) {
    return (
        <nav className="relative z-10 w-full max-w-7xl mx-auto px-4 sm:px-6 py-6 flex justify-between items-center gap-4 text-sm print:hidden">
            <Link href="/" className="flex items-center gap-2 font-semibold tracking-tight text-gray-200 hover:text-white transition-colors">
                <span className="h-6 w-6 bg-white rounded-full flex items-center justify-center text-black font-bold text-xs">S</span>
                SynapseAI
            </Link>
            <div className="flex items-center gap-3 min-w-0">{children}</div>
        </nav>
    );
}
