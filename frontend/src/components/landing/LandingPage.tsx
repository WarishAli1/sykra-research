"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import {
  ArrowRight, BookOpen, ChevronDown, FileText, FileUp, History, Menu, Network,
  Search, ShieldCheck, X, Download, PenLine, Quote, Workflow,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

// TODO(before launch): the "private data" and "free tier" FAQ answers still contain placeholder text. Fill in your real policy and pricing.
const faqs = [
  ["How accurate are the citations?", "Sykra links claims to papers retrieved from your library or the open literature, so you can inspect the source behind every answer. Always review important conclusions before publishing."],
  ["Is my research data private?", "Your workspace is designed for your research. We do not use your private uploads to train public models. Replace this placeholder with your final data retention and security policy."],
  ["What file types can I upload?", "PDF is supported today, with more research formats planned. You can also search the open literature without uploading anything."],
  ["Is there a free tier?", "You can explore the product before committing. Add your final plan limits and pricing details here when they are ready."],
  ["How is this different from a general chatbot?", "Sykra is built around evidence: your papers, scholarly search, visible sources, and exportable answers—not confident-sounding guesses."],
  ["What can I export?", "Export-ready answers can become a PDF or a clean document for your writing workflow. Add your final format list here."],
  ["Who is Sykra for?", "Researchers, graduate students, analysts, and anyone who needs to move from a question to defensible evidence faster."],
];

const steps = [
  { num: "01", title: "Ask & Research", text: "Ask using your uploaded documents, the internet, or both. Choose a Direct Answer for speed or a Researched Answer for a detailed, cited response. References always come last.", icon: Search },
  { num: "02", title: "Refine & Export", text: "Review your answers, verify the references, then export your research as a standard PDF or an academic PDF in LaTeX format.", icon: Download },
  { num: "03", title: "Knowledge Graph", text: "Explore how papers connect through methods, datasets, authors and concepts. Spot relationships between studies and gaps worth researching.", icon: Network },
  { num: "04", title: "Sykra Studio", text: "Create graphs, data flow diagrams, flowcharts, research frameworks and system architecture diagrams in a dedicated visual workspace.", icon: PenLine },
];

// Desktop layout (xl and up). The container is a fixed 1216px wide there, so these are plain pixel coordinates
// and the SVG draws 1:1. The path runs diagonally from top-left to bottom-right.
const STAGE_H = 880;
const stepPositions = [
  { x: 100, y: 320 },
  { x: 370, y: 485 },
  { x: 640, y: 650 },
  { x: 910, y: 815 },
] as const;

const PATH_D = "M0 240 C45 240 55 320 100 320 C235 320 235 485 370 485 C505 485 505 650 640 650 C775 650 775 815 910 815 C985 815 1010 840 1090 845";

function BrandLogo({ variant, size }: { variant: "light" | "dark"; size: "navbar" | "footer" }) {
  const light = variant === "light";
  return <span className={`inline-flex items-center ${size === "navbar" ? "gap-2.5" : "gap-2.5"}`}>
    <img src="/sykra-logo.svg" alt="" width={size === "navbar" ? 32 : 36} height={size === "navbar" ? 32 : 36} className={`${size === "navbar" ? "h-8 w-8" : "h-9 w-9"} shrink-0 object-contain ${light ? "brightness-0 invert" : ""}`} />
    <span className={`font-serif text-[22px] font-medium tracking-tight ${light ? "text-mint" : "text-ink"} max-[400px]:hidden`}>Sykra Research</span>
  </span>;
}

function LogoLink({ variant, size }: { variant: "light" | "dark"; size: "navbar" | "footer" }) {
  return <Link href="/" aria-label="Sykra Research home" className="inline-flex items-center rounded-md focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"><BrandLogo variant={variant} size={size} /></Link>;
}

function Container({ children, className = "", id }: { children: ReactNode; className?: string; id?: string }) {
  return <div id={id} className={`mx-auto w-full max-w-7xl px-6 lg:px-8 ${className}`}>{children}</div>;
}

function Navbar() {
  const [open, setOpen] = useState(false);
  const [signedIn, setSignedIn] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const base = (process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000/api").replace(/\/$/, "");
    fetch(`${base}/auth/me`, { credentials: "include" }).then((response) => setSignedIn(response.ok)).catch(() => setSignedIn(false));
    const handleScroll = () => setScrolled(window.scrollY > 8);
    handleScroll();
    window.addEventListener("scroll", handleScroll, { passive: true });
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);
  return <header className={`sticky top-0 z-50 bg-white/80 backdrop-blur-md transition-colors ${scrolled ? "border-b border-line/70" : "border-b border-transparent"}`}>
    <Container className="grid h-[72px] grid-cols-[1fr_auto_1fr] items-center">
      <LogoLink variant="dark" size="navbar" />
      <nav className="hidden items-center gap-8 text-sm font-medium text-ink-muted md:flex">
        <a href="#features" className="transition hover:text-ink">Features</a><a href="#how-it-works" className="transition hover:text-ink">How it works</a><a href="#faq" className="transition hover:text-ink">FAQ</a>
      </nav>
      <div className="hidden items-center justify-self-end gap-5 md:flex">{signedIn ? <Link href="/app/dashboard" className="text-sm font-semibold text-ink-muted hover:text-ink">Dashboard</Link> : <Link href="/login" className="text-sm font-semibold text-ink-muted hover:text-ink">Login</Link>}<Link href={signedIn ? "/app/dashboard" : "/app"} className="button-primary">Open App <ArrowRight className="h-4 w-4" /></Link></div>
      <button className="rounded-lg p-2 text-ink md:hidden" aria-label={open ? "Close menu" : "Open menu"} onClick={() => setOpen(!open)}>{open ? <X /> : <Menu />}</button>
    </Container>
    {open && <Container className="border-t border-line py-4 md:hidden"><nav className="flex flex-col gap-4 text-sm font-semibold"><a href="#features" onClick={() => setOpen(false)}>Features</a><a href="#how-it-works" onClick={() => setOpen(false)}>How it works</a><a href="#faq" onClick={() => setOpen(false)}>FAQ</a>{!signedIn && <Link href="/login">Login</Link>}{signedIn && <Link href="/app/dashboard">Dashboard</Link>}<Link href={signedIn ? "/app/dashboard" : "/app"} className="button-primary w-fit">Open App <ArrowRight className="h-4 w-4" /></Link></nav></Container>}
  </header>;
}

const orbits = [
  { inset: "0%", duration: "46s", reverse: false, dots: [{ size: 12, at: "top" }, { size: 6, at: "bottom" }] },
  { inset: "12%", duration: "32s", reverse: true, dots: [{ size: 10, at: "top" }] },
  { inset: "25%", duration: "22s", reverse: false, dots: [{ size: 8, at: "top" }, { size: 5, at: "bottom" }] },
];

function Orbits() {
  return <div className="orbits" aria-hidden="true">
    {orbits.map((orbit, i) => <div key={i} className="orbit" style={{ inset: orbit.inset }}>
      <div className="orbit-arm" style={{ animationDuration: orbit.duration, animationDirection: orbit.reverse ? "reverse" : "normal" }}>
        {orbit.dots.map((dot, j) => <span key={j} className="orbit-dot" style={{ width: dot.size, height: dot.size, top: dot.at === "top" ? 0 : "100%" }} />)}
      </div>
    </div>)}
  </div>;
}

function Hero() {
  return <section className="hero-grid overflow-hidden">
    <Container className="relative isolate py-20 text-center sm:py-28">
      <Orbits />
      <p className="eyebrow mb-5">Your research, with receipts</p>
      <h1 className="mx-auto max-w-4xl font-serif text-5xl leading-[1.04] tracking-[-0.045em] text-ink sm:text-7xl">Go from question to <span className="text-accent underline decoration-accent/30 underline-offset-8">cited answer</span> in seconds.</h1>
      <p className="mx-auto mt-7 max-w-2xl text-base leading-7 text-ink-muted sm:text-lg">Ask across your papers and the open literature—without risking a fake citation. Every claim links to a real paper, so your next step is always clear.</p>
      <div className="mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row"><Link href="/app" className="button-primary px-6 py-3.5">Open App <ArrowRight className="h-4 w-4" /></Link><a href="#demo" className="button-secondary px-6 py-3.5"><span className="grid h-5 w-5 place-items-center rounded-full bg-mint text-[10px]">▶</span> Watch demo</a></div>
      <p className="mt-4 text-xs font-medium text-ink-muted">No credit card <span className="mx-2 text-sage">·</span> Every answer cited</p>
      <DemoPreview />
    </Container>
  </section>;
}

function DemoPreview() {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [started, setStarted] = useState(false);
  const start = () => {
    const video = videoRef.current;
    if (!video) return;
    setStarted(true);
    video.muted = false;
    video.play().catch(() => { video.muted = true; video.play().catch(() => undefined); });
  };
  return <div id="demo" className="relative mx-auto mt-20 max-w-5xl scroll-mt-24 text-left">
    <div aria-hidden="true" className="absolute inset-x-12 -top-6 h-24 rounded-[32px] border border-sage/20 bg-mint/40" />
    <div aria-hidden="true" className="absolute inset-x-6 -top-3 h-24 rounded-[32px] border border-sage/30 bg-mint/70" />
    <div className="relative rounded-[28px] border border-sage/40 bg-white p-2 shadow-[0_30px_70px_rgba(5,31,32,.16)]">
      <div className="relative overflow-hidden rounded-[22px] bg-forest">
        <video ref={videoRef} className="block aspect-video w-full object-cover" controls={started} muted playsInline preload="metadata" onEnded={() => setStarted(false)}><source src="/demo.mp4#t=0.1" type="video/mp4" />Your browser does not support embedded video.</video>
        {!started && <button type="button" aria-label="Play demo video" onClick={start} className="group absolute inset-0 grid place-items-center bg-transparent transition-colors hover:bg-forest/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"><span className="grid h-14 w-14 place-items-center rounded-full bg-forest/90 text-white shadow-lg ring-4 ring-white/50 backdrop-blur-sm transition-transform group-hover:scale-105"><svg viewBox="0 0 24 24" className="ml-0.5 h-5 w-5 fill-current" aria-hidden="true"><path d="M8 5v14l11-7z" /></svg></span></button>}
      </div>
    </div>
  </div>;
}

const capabilities = [
  { icon: Quote, label: "Cited answers" },
  { icon: BookOpen, label: "Two Answer Modes" },
  { icon: FileUp, label: "Documents + Web" },
  { icon: Download, label: "PDF + LaTeX" },
];

// TODO(before launch): the testimonials and stats in SocialProof are PLACEHOLDERS. Replace them with real, approved proof (or remove them).
function SocialProof() {
  return <section><Container className="py-20 sm:py-28"><p className="eyebrow text-center">BUILT FOR RESEARCH</p><ul className="mx-auto mt-10 grid max-w-4xl grid-cols-2 gap-y-6 lg:grid-cols-4 lg:divide-x lg:divide-line">{capabilities.map(({ icon: Icon, label }) => <li key={label} className="flex items-center justify-center gap-2.5 px-4 text-sm font-medium text-ink-muted"><Icon className="h-4 w-4 shrink-0 text-sage" aria-hidden="true" />{label}</li>)}</ul><div className="mt-16 grid gap-4 md:grid-cols-3">{[["Dr. Maya Chen","Postdoctoral researcher","Cut literature review time from 2 weeks to 2 days."],["Jon Bell","PhD candidate, Biology","I can finally show exactly where every claim came from."],["Priya Nair","Research lead","The graph helped our team spot the missing connection." ]].map(([name,role,quote]) => <blockquote key={name} className="rounded-2xl border border-line bg-white p-6 shadow-soft"><div className="mb-5 flex gap-1 text-accent">★★★★★</div><p className="font-serif text-lg leading-7 text-ink">“{quote}”</p><footer className="mt-6 text-xs text-ink-muted"><strong className="block text-sm text-ink">{name}</strong>{role}</footer></blockquote>)}</div><div className="mt-12 grid grid-cols-3 divide-x divide-line rounded-2xl border border-line bg-mint/30 py-6 text-center"><div><strong className="block font-serif text-3xl text-forest">2.4M</strong><span className="text-xs text-ink-muted">papers indexed</span></div><div><strong className="block font-serif text-3xl text-forest">98%</strong><span className="text-xs text-ink-muted">citations verified</span></div><div><strong className="block font-serif text-3xl text-forest">11h</strong><span className="text-xs text-ink-muted">saved per review</span></div></div><p className="mt-3 text-center text-[10px] text-ink-muted">TODO: Replace placeholder logos, testimonials, and stats with approved proof.</p></Container></section>;
}

function Problem() {
  return <section className="bg-forest py-20 text-mint sm:py-28"><Container><div className="max-w-2xl"><p className="eyebrow text-sage">The hidden cost of scattered research</p><h2 className="mt-4 font-serif text-4xl leading-tight tracking-tight sm:text-5xl">Your best thinking shouldn&apos;t get lost in the hunt.</h2></div><div className="mt-12 grid gap-4 md:grid-cols-3">{[["Scattered PDFs","The answer is somewhere in six tabs, three folders, and an old download.","Hours disappear before the real work begins."],["Unclear citations","A polished answer with a source that doesn&apos;t quite say it.","Your credibility takes the hit."],["Missed connections","The important paper never made it into your search results.","Good ideas arrive too late."]].map(([title,text,cost],i) => <div key={title} className="rounded-2xl border border-mint/15 bg-forest-light/30 p-6"><span className="font-serif text-4xl text-sage">0{i+1}</span><h3 className="mt-8 text-xl font-semibold">{title}</h3><p className="mt-3 text-sm leading-6 text-mint/70">{text}</p><p className="mt-8 border-t border-mint/15 pt-4 text-sm font-semibold text-mint">{cost}</p></div>)}</div></Container></section>;
}

type FeatureItem = { icon: LucideIcon; title: string; text: string };

function FeatureRow({ title, subtitle, items, panelClass, flip = false, children }: { title: string; subtitle: string; items: FeatureItem[]; panelClass: string; flip?: boolean; children: ReactNode }) {
  return <div className={`grid items-center gap-10 lg:gap-16 ${flip ? "lg:grid-cols-[7fr_5fr]" : "lg:grid-cols-[5fr_7fr]"}`}>
    <div className={flip ? "lg:order-2" : ""}>
      <h3 className="font-serif text-3xl leading-tight tracking-tight text-ink sm:text-4xl">{title}</h3>
      <p className="mt-3 text-base leading-7 text-ink-muted">{subtitle}</p>
      <ul className="mt-8 grid gap-x-8 gap-y-6 sm:grid-cols-2">{items.map(({ icon: Icon, title: itemTitle, text }) => <li key={itemTitle}><div className="flex items-center gap-2 text-sm font-semibold text-ink"><Icon className="h-4 w-4 text-forest" />{itemTitle}</div><p className="mt-1.5 text-xs leading-5 text-ink-muted">{text}</p></li>)}</ul>
      <Link href="/app" className="mt-8 inline-flex items-center gap-2 font-mono text-[11px] font-semibold uppercase tracking-[0.14em] text-forest transition hover:text-accent-landing">Try it in the app <ArrowRight className="h-3.5 w-3.5" /></Link>
    </div>
    <div className={`rounded-3xl p-5 sm:p-8 ${flip ? "lg:order-1" : ""} ${panelClass}`}>{children}</div>
  </div>;
}

function Shot({ src, alt, width, height }: { src: string; alt: string; width: number; height: number }) {
  return <img src={src} alt={alt} width={width} height={height} loading="lazy" className="block h-auto w-full rounded-xl shadow-[0_20px_44px_rgba(5,31,32,.14)] ring-1 ring-forest/10" />;
}

function ExportMock() {
  const line = "h-1.5 rounded-full bg-ink/10";
  return <div className="mx-auto grid min-h-[300px] max-w-lg grid-cols-2 items-center gap-4 sm:gap-6" role="img" aria-label="A standard PDF and an academic LaTeX PDF, each ending with references">
    <div className="-rotate-2 rounded-lg bg-white p-4 shadow-soft ring-1 ring-black/5 sm:p-5">
      <p className="text-[9px] font-bold uppercase tracking-widest text-ink-muted">Standard PDF</p>
      <div className="mt-3 h-2.5 w-3/4 rounded-full bg-forest/80" />
      <div className="mt-4 space-y-2"><div className={line} /><div className={line} /><div className={`${line} w-5/6`} /><div className={line} /><div className={`${line} w-2/3`} /></div>
      <p className="mt-5 text-[9px] font-bold uppercase tracking-widest text-forest">References</p>
      <div className="mt-2 space-y-1.5"><div className={`${line} w-11/12`} /><div className={`${line} w-4/5`} /><div className={`${line} w-10/12`} /></div>
    </div>
    <div className="rotate-2 rounded-lg bg-white p-4 shadow-soft ring-1 ring-black/5 sm:p-5">
      <p className="text-[9px] font-bold uppercase tracking-widest text-ink-muted">Academic · LaTeX</p>
      <div className="mx-auto mt-3 h-2.5 w-3/4 rounded-full bg-forest/80" />
      <p className="mt-3 text-center font-serif text-[9px] italic text-ink-muted">Abstract</p>
      <div className="mt-2 space-y-1.5"><div className={line} /><div className={line} /><div className={`${line} w-4/5`} /></div>
      <div className="mt-4 grid grid-cols-2 gap-3"><div className="space-y-1.5"><div className={line} /><div className={line} /><div className={`${line} w-5/6`} /><div className={line} /></div><div className="space-y-1.5"><div className={line} /><div className={`${line} w-4/5`} /><div className={line} /><div className={`${line} w-2/3`} /></div></div>
      <p className="mt-4 font-serif text-[9px] font-bold text-forest">References</p>
      <div className="mt-2 space-y-1.5"><div className={`${line} w-11/12`} /><div className={`${line} w-4/5`} /><div className={`${line} w-10/12`} /></div>
    </div>
  </div>;
}

function Solution() {
  return <section id="features" className="scroll-mt-24"><Container className="py-20 sm:py-28">
    <div className="max-w-2xl"><p className="eyebrow">A better research loop</p><h2 className="mt-4 font-serif text-4xl leading-tight tracking-tight sm:text-5xl">Less searching. More understanding.</h2><p className="mt-5 text-base leading-7 text-ink-muted">Sykra brings the pieces together so you can spend your time evaluating ideas—not hunting for them.</p></div>
    <div className="mt-16 space-y-20 sm:space-y-28">
      <FeatureRow title="Ask your papers or the open literature." subtitle="Direct for a quick answer, Researched for the full picture." panelClass="bg-indigo-tint" items={[
        { icon: FileUp, title: "Documents, web, or both", text: "Ground answers in your PDFs, the open literature, or both." },
        { icon: Search, title: "Direct answers", text: "A clear, concise answer with references listed at the end." },
        { icon: BookOpen, title: "Researched answers", text: "A detailed, cited write-up with every reference at the end." },
        { icon: ShieldCheck, title: "Literature only mode", text: "Keep answers anchored to published research." },
      ]}><Shot src="/chat.webp" alt="Sykra chat showing a direct answer next to a library of cited papers" width={1600} height={910} /></FeatureRow>

      <FeatureRow flip title="See how papers connect." subtitle="An explorable graph of papers, methods and datasets." panelClass="bg-accent-tint" items={[
        { icon: Network, title: "Methods and datasets", text: "See how papers connect and which methods and datasets they use." },
        { icon: BookOpen, title: "Topic clusters", text: "Related papers are grouped by subject and sized by influence." },
        { icon: Search, title: "Ask the graph", text: "Search the graph in plain language." },
        { icon: ArrowRight, title: "Trace paths", text: "Follow a route between any two papers." },
      ]}><Shot src="/graph.webp" alt="Sykra knowledge graph linking papers, topics, methods and datasets" width={1600} height={911} /></FeatureRow>

      <FeatureRow title="Build diagrams in Sykra Studio." subtitle="Graphs, DFDs and flowcharts, made for research." panelClass="bg-gold-tint" items={[
        { icon: Workflow, title: "Flowcharts and DFDs", text: "Draw processes and data flows as you think them through." },
        { icon: Network, title: "Graphs and architecture", text: "Research frameworks and system architecture diagrams." },
        { icon: PenLine, title: "Live preview", text: "Watch the diagram update as you edit nodes and flows." },
        { icon: History, title: "Saved history", text: "Reopen and continue earlier diagrams." },
      ]}><Shot src="/studio.webp" alt="Sykra Studio editor with a live diagram preview" width={1600} height={909} /></FeatureRow>

      <FeatureRow flip title="Take your work with you." subtitle="Export any answer as a standard or academic PDF." panelClass="bg-mint" items={[
        { icon: Download, title: "Standard PDF", text: "A clean, readable export for sharing and meetings." },
        { icon: FileText, title: "Academic PDF", text: "Typeset with LaTeX for papers and theses." },
        { icon: Quote, title: "References included", text: "Every answer ends with its sources." },
        { icon: PenLine, title: "Ready for your draft", text: "Carry sourced answers straight into your writing." },
      ]}><ExportMock /></FeatureRow>
    </div>
  </Container></section>;
}

type StepIcon = (typeof steps)[number]["icon"];

// Scroll progress of an element: 0 when its top is at `anchor` of the viewport height, 1 when its bottom is.
function useScrollProgress<T extends HTMLElement>(ref: { current: T | null }, anchor = 0.65) {
  const [progress, setProgress] = useState(0);
  useEffect(() => {
    let frame = 0;
    const update = () => {
      frame = 0;
      const el = ref.current;
      if (!el) return;
      const rect = el.getBoundingClientRect();
      if (rect.height === 0) { setProgress(0); return; }
      const next = Math.min(1, Math.max(0, (window.innerHeight * anchor - rect.top) / rect.height));
      setProgress((prev) => (Math.abs(prev - next) < 0.002 ? prev : next));
    };
    const onScroll = () => { if (!frame) frame = requestAnimationFrame(update); };
    update();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
      if (frame) cancelAnimationFrame(frame);
    };
  }, [ref, anchor]);
  return progress;
}

function StepNode({ Icon, active }: { Icon: StepIcon; active: boolean }) {
  return <span className={`grid h-14 w-14 place-items-center rounded-2xl bg-white transition-shadow duration-500 ${active ? "shadow-[0_10px_30px_rgba(217,119,87,.3)]" : "shadow-soft"}`}>
    <span className={`grid h-8 w-8 place-items-center rounded-full transition-colors duration-500 ${active ? "bg-accent-landing text-white" : "bg-[#c9d1cc] text-white"}`}><Icon className="h-4 w-4" /></span>
  </span>;
}

function WavePath() {
  const stageRef = useRef<HTMLDivElement>(null);
  const pathRef = useRef<SVGPathElement>(null);
  const progress = useScrollProgress(stageRef);
  const [stops, setStops] = useState<number[]>([0.1, 0.36, 0.62, 0.88]);

  // Find where along the path each node sits, so a node lights up exactly when the line reaches it.
  useEffect(() => {
    const measure = () => {
      const path = pathRef.current;
      if (!path) return;
      try {
        const total = path.getTotalLength();
        if (!total) return;
        const samples = 500;
        setStops(stepPositions.map(({ x, y }) => {
          let best = 0;
          let bestDist = Infinity;
          for (let i = 0; i <= samples; i++) {
            const pt = path.getPointAtLength((total * i) / samples);
            const dist = (pt.x - x) ** 2 + (pt.y - y) ** 2;
            if (dist < bestDist) { bestDist = dist; best = i / samples; }
          }
          return best;
        }));
      } catch { /* path not rendered yet */ }
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, []);

  return <div ref={stageRef} className="relative mt-16 hidden xl:block" style={{ height: STAGE_H }}>
    <svg className="absolute inset-0 h-full w-full overflow-visible" viewBox={`0 0 1216 ${STAGE_H}`} aria-hidden="true">
      <defs>
        <filter id="line-reflection" filterUnits="userSpaceOnUse" x="-120" y="-120" width="1456" height={STAGE_H + 240}><feGaussianBlur stdDeviation="10" /></filter>
      </defs>
      <path d={PATH_D} fill="none" stroke="rgba(142,182,155,.4)" strokeWidth="9" strokeLinecap="round" transform="translate(0 22)" filter="url(#line-reflection)" />
      <path d={PATH_D} pathLength={1} fill="none" stroke="rgba(217,119,87,.5)" strokeWidth="9" strokeLinecap="round" strokeDasharray="1 1" strokeDashoffset={1 - progress} transform="translate(0 22)" filter="url(#line-reflection)" style={{ opacity: progress > 0.004 ? 1 : 0 }} />
      <path ref={pathRef} d={PATH_D} fill="none" stroke="rgba(142,182,155,.5)" strokeWidth="3" strokeLinecap="round" />
      <path d={PATH_D} pathLength={1} fill="none" stroke="var(--accent-landing)" strokeWidth="3" strokeLinecap="round" strokeDasharray="1 1" strokeDashoffset={1 - progress} style={{ opacity: progress > 0.004 ? 1 : 0 }} />
    </svg>
    {steps.map((step, i) => {
      const { x, y } = stepPositions[i];
      const active = progress >= stops[i] - 0.01;
      return <div key={step.num}>
        <div className="absolute -translate-x-1/2 -translate-y-1/2" style={{ left: x, top: y }}><StepNode Icon={step.icon} active={active} /></div>
        <div className={`absolute w-[236px] transition-all duration-500 ${active ? "translate-y-0 opacity-100" : "translate-y-2 opacity-40"}`} style={{ left: x + 34, bottom: STAGE_H - y + 22 }}>
          <span aria-hidden="true" className="pointer-events-none absolute -bottom-6 right-0 select-none font-serif text-[104px] leading-none text-sage/20">{step.num}</span>
          <div className="relative"><h3 className="font-semibold text-ink">{step.title}</h3><p className="mt-2 text-sm leading-6 text-ink-muted">{step.text}</p></div>
        </div>
      </div>;
    })}
  </div>;
}

function VerticalPath() {
  const listRef = useRef<HTMLOListElement>(null);
  const trackRef = useRef<HTMLSpanElement>(null);
  const progress = useScrollProgress(trackRef);
  const [stops, setStops] = useState<number[]>([0, 0.33, 0.66, 1]);

  useEffect(() => {
    const measure = () => {
      const list = listRef.current;
      const track = trackRef.current;
      if (!list || !track || !track.offsetHeight) return;
      const items = Array.from(list.querySelectorAll<HTMLElement>("[data-step]"));
      setStops(items.map((el) => el.offsetTop / track.offsetHeight));
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, []);

  return <ol ref={listRef} className="relative mx-auto mt-12 max-w-xl space-y-10 xl:hidden">
    <span ref={trackRef} aria-hidden="true" className="absolute bottom-7 left-7 top-7 w-0.5 -translate-x-1/2 rounded-full bg-sage/40">
      <span className="block h-full w-full origin-top rounded-full bg-accent-landing shadow-[8px_0_16px_rgba(217,119,87,.35)]" style={{ transform: `scaleY(${progress})` }} />
    </span>
    {steps.map((step, i) => {
      const active = progress >= stops[i] - 0.01;
      return <li key={step.num} data-step className="relative flex gap-5">
        <div className="relative z-10 shrink-0"><StepNode Icon={step.icon} active={active} /></div>
        <div className={`relative pt-1 transition-opacity duration-500 ${active ? "opacity-100" : "opacity-50"}`}>
          <span aria-hidden="true" className="pointer-events-none absolute -top-2 right-0 select-none font-serif text-7xl leading-none text-sage/20">{step.num}</span>
          <h3 className="relative font-semibold text-ink">{step.title}</h3><p className="relative mt-2 text-sm leading-6 text-ink-muted">{step.text}</p>
        </div>
      </li>;
    })}
  </ol>;
}

function HowItWorks() {
  return <section id="how-it-works" className="scroll-mt-24 overflow-hidden border-y border-line bg-mint/20"><Container className="py-20 sm:py-28">
    <div className="text-center"><p className="eyebrow">How it works</p><h2 className="mt-4 font-serif text-4xl tracking-tight sm:text-5xl">How Sykra Research works.</h2><p className="mx-auto mt-5 max-w-xl text-base leading-7 text-ink-muted">From your first question to a finished, citable piece of research.</p></div>
    <WavePath />
    <VerticalPath />
  </Container></section>;
}

function FAQ() {
  const [active, setActive] = useState<number | null>(0);
  return <section id="faq" className="scroll-mt-24"><Container className="py-20 sm:py-28"><div className="mx-auto max-w-3xl"><div className="text-center"><p className="eyebrow">Questions, answered</p><h2 className="mt-4 font-serif text-4xl tracking-tight sm:text-5xl">Before you begin.</h2></div><div className="mt-12 divide-y divide-line border-y border-line">{faqs.map(([question,answer],i) => <div key={question}><button className="flex w-full items-center justify-between gap-6 py-5 text-left font-semibold text-ink" onClick={() => setActive(active === i ? null : i)} aria-expanded={active === i}>{question}<ChevronDown className={`h-4 w-4 shrink-0 text-ink-muted transition-transform ${active === i ? "rotate-180" : ""}`} /></button>{active === i && <p className="max-w-2xl pb-5 pr-10 text-sm leading-6 text-ink-muted">{answer}</p>}</div>)}</div></div></Container></section>;
}

// Footer links with a real destination. Anything not listed renders as plain text instead of jumping to top.
const footerLinks: Record<string, string> = {
  "Features": "#features",
  "How it works": "#how-it-works",
  "Open app": "/app",
};

function Footer() {
  return <footer className="bg-deep text-mint">
    <Container id="final-cta" className="border-b border-mint/15 py-20 text-center sm:py-28">
      <p className="eyebrow text-sage">Make the next question count</p>
      <h2 className="mx-auto mt-4 max-w-2xl font-serif text-4xl leading-tight tracking-tight sm:text-6xl">Your next literature review starts with one question.</h2>
      <Link href="/app" className="button-primary mt-9 px-6 py-3.5">Open App <ArrowRight className="h-4 w-4" /></Link>
    </Container>
    <Container className="grid gap-12 py-12 lg:grid-cols-[1.5fr_1fr_1fr_1fr]">
      <div><LogoLink variant="light" size="footer" /><p className="mt-4 max-w-xs text-sm leading-6 text-mint/60">A calmer, more credible way to move through research.</p></div>
      {[["Product","Features","How it works","Open app"],["Company","About Sykra","Contact","Careers"],["Legal","Privacy","Terms","Security"]].map(([heading,...links]) => <div key={heading}><h3 className="text-xs font-semibold uppercase tracking-widest text-sage">{heading}</h3><div className="mt-4 space-y-3 text-sm text-mint/60">{links.map(link => {
        const href = footerLinks[link];
        return href ? <a href={href} key={link} className="block hover:text-mint">{link}</a> : <span key={link} className="block cursor-default">{link}</span>;
      })}</div></div>)}
    </Container>
    <Container className="flex flex-col gap-3 border-t border-mint/15 py-5 text-xs text-mint/40 sm:flex-row sm:justify-between">
      <span>© 2026 Sykra Research. All rights reserved.</span><span>Built for evidence-led work.</span>
    </Container>
  </footer>;
}

export default function LandingPage() {
  return <main><Navbar /><Hero /><SocialProof /><Problem /><Solution /><HowItWorks /><FAQ /><Footer /></main>;
}