"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import {
  ArrowRight, BookOpen, ChevronDown, FileUp, Menu, Network,
  Search, ShieldCheck, X, Download, PenLine, Quote,
} from "lucide-react";

const features = [
  { icon: Quote, title: "Answers you can defend", text: "Every claim links back to the exact paper and passage that supports it." },
  { icon: BookOpen, title: "One calm home for papers", text: "Keep your PDFs, notes, and research questions together in your Library." },
  { icon: Network, title: "See the field at a glance", text: "Follow ideas, authors, and citations through an explorable research graph." },
  { icon: PenLine, title: "Turn findings into drafts", text: "Shape evidence into briefs, outlines, and literature reviews in Studio." },
  { icon: FileUp, title: "Ground answers in your PDFs", text: "Drop in a paper and ask questions without losing the source context." },
  { icon: ShieldCheck, title: "Stay in the literature", text: "Literature-only mode keeps answers anchored to published research." },
  { icon: Download, title: "Leave with work that travels", text: "Export clean, citation-ready output for your next draft or meeting." },
  { icon: Search, title: "Find what you missed", text: "Search the open literature to surface relevant papers beyond your stack." },
];

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
  { num: "01", title: "Ask or drop a PDF", text: "Start with the question already on your mind.", icon: Search },
  { num: "02", title: "Get a cited answer", text: "See the reasoning and source papers together.", icon: Quote },
  { num: "03", title: "Explore the graph", text: "Follow the people and ideas around your question.", icon: Network },
  { num: "04", title: "Export your work", text: "Take a clean, sourced answer into your draft.", icon: Download },
];

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

function Hero() {
  return <section className="hero-grid overflow-hidden">
    <Container className="relative py-20 text-center sm:py-28">
      <div className="network-mark" aria-hidden="true" />
      <p className="eyebrow mb-5">Your research, with receipts</p>
      <h1 className="mx-auto max-w-4xl font-serif text-5xl leading-[1.04] tracking-[-0.045em] text-ink sm:text-7xl">Go from question to <span className="text-accent underline decoration-accent/30 underline-offset-8">cited answer</span> in seconds.</h1>
      <p className="mx-auto mt-7 max-w-2xl text-base leading-7 text-ink-muted sm:text-lg">Ask across your papers and the open literature—without risking a fake citation. Every claim links to a real paper, so your next step is always clear.</p>
      <div className="mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row"><Link href="/app" className="button-primary px-6 py-3.5">Open App <ArrowRight className="h-4 w-4" /></Link><a href="#demo" className="button-secondary px-6 py-3.5"><span className="grid h-5 w-5 place-items-center rounded-full bg-mint text-[10px]">▶</span> Watch demo</a></div>
      <p className="mt-4 text-xs font-medium text-ink-muted">No credit card <span className="mx-2 text-sage">·</span> Every answer cited</p>
      <div id="demo" className="browser-preview mx-auto mt-14 block max-w-5xl overflow-hidden text-left"><div className="flex items-center gap-1.5 border-b border-mint/20 bg-forest px-4 py-3"><i /><i /><i /><span className="ml-3 rounded-md bg-forest-light/50 px-3 py-1 text-[10px] text-mint/70">app.sykraresearch.com</span></div><video className="block aspect-video w-full bg-forest object-cover" controls muted playsInline preload="metadata"><source src="/demo.mp4" type="video/mp4" />Your browser does not support embedded video.</video></div>
    </Container>
  </section>;
}

function SocialProof() {
  return <section><Container className="py-20 sm:py-28"><p className="eyebrow text-center">Built for careful thinkers</p><div className="mt-8 flex flex-wrap items-center justify-center gap-x-10 gap-y-5 text-sm font-serif font-semibold text-ink-muted/60 sm:gap-x-16"><span>◈ NORTHWESTERN</span><span>◒ MIT MEDIA LAB</span><span>◉ OXFORD</span><span>△ STANFORD</span><span>◌ OPENSCIENCE</span></div><div className="mt-16 grid gap-4 md:grid-cols-3">{[["Dr. Maya Chen","Postdoctoral researcher","Cut literature review time from 2 weeks to 2 days."],["Jon Bell","PhD candidate, Biology","I can finally show exactly where every claim came from."],["Priya Nair","Research lead","The graph helped our team spot the missing connection." ]].map(([name,role,quote]) => <blockquote key={name} className="rounded-2xl border border-line bg-white p-6 shadow-soft"><div className="mb-5 flex gap-1 text-accent">★★★★★</div><p className="font-serif text-lg leading-7 text-ink">“{quote}”</p><footer className="mt-6 text-xs text-ink-muted"><strong className="block text-sm text-ink">{name}</strong>{role}</footer></blockquote>)}</div><div className="mt-12 grid grid-cols-3 divide-x divide-line rounded-2xl border border-line bg-mint/30 py-6 text-center"><div><strong className="block font-serif text-3xl text-forest">2.4M</strong><span className="text-xs text-ink-muted">papers indexed</span></div><div><strong className="block font-serif text-3xl text-forest">98%</strong><span className="text-xs text-ink-muted">citations verified</span></div><div><strong className="block font-serif text-3xl text-forest">11h</strong><span className="text-xs text-ink-muted">saved per review</span></div></div><p className="mt-3 text-center text-[10px] text-ink-muted">TODO: Replace placeholder logos, testimonials, and stats with approved proof.</p></Container></section>;
}

function Problem() {
  return <section className="bg-forest py-20 text-mint sm:py-28"><Container><div className="max-w-2xl"><p className="eyebrow text-sage">The hidden cost of scattered research</p><h2 className="mt-4 font-serif text-4xl leading-tight tracking-tight sm:text-5xl">Your best thinking shouldn&apos;t get lost in the hunt.</h2></div><div className="mt-12 grid gap-4 md:grid-cols-3">{[["Scattered PDFs","The answer is somewhere in six tabs, three folders, and an old download.","Hours disappear before the real work begins."],["Unclear citations","A polished answer with a source that doesn&apos;t quite say it.","Your credibility takes the hit."],["Missed connections","The important paper never made it into your search results.","Good ideas arrive too late."]].map(([title,text,cost],i) => <div key={title} className="rounded-2xl border border-mint/15 bg-forest-light/30 p-6"><span className="font-serif text-4xl text-sage">0{i+1}</span><h3 className="mt-8 text-xl font-semibold">{title}</h3><p className="mt-3 text-sm leading-6 text-mint/70">{text}</p><p className="mt-8 border-t border-mint/15 pt-4 text-sm font-semibold text-mint">{cost}</p></div>)}</div></Container></section>;
}

function Solution() {
  return <section id="features"><Container className="py-20 sm:py-28"><div className="max-w-2xl"><p className="eyebrow">A better research loop</p><h2 className="mt-4 font-serif text-4xl leading-tight tracking-tight sm:text-5xl">Less searching. More understanding.</h2><p className="mt-5 text-base leading-7 text-ink-muted">Sykra brings the pieces together so you can spend your time evaluating ideas—not hunting for them.</p></div><div className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">{features.map(({icon: Icon,title,text}) => <article key={title} className="feature-card"><span className="grid h-11 w-11 place-items-center rounded-xl bg-mint text-forest"><Icon className="h-5 w-5" /></span><h3 className="mt-5 text-lg font-semibold tracking-tight text-ink">{title}</h3><p className="mt-2 text-sm leading-6 text-ink-muted">{text}</p></article>)}</div></Container></section>;
}

function HowItWorks() {
  return <section id="how-it-works" className="border-y border-line bg-mint/20"><Container className="py-20 sm:py-28"><div className="text-center"><p className="eyebrow">How it works</p><h2 className="mt-4 font-serif text-4xl tracking-tight sm:text-5xl">From first question to next step.</h2></div><div className="mt-14 grid gap-8 md:grid-cols-4">{steps.map(({ num, title, text, icon: Icon }) => <div key={num} className="relative text-center md:text-left"><span className="font-serif text-5xl text-sage">{num}</span><div className="mt-5 grid h-10 w-10 place-items-center rounded-xl bg-white text-forest shadow-sm"><Icon className="h-4 w-4" /></div><h3 className="mt-5 font-semibold text-ink">{title}</h3><p className="mt-2 text-sm leading-6 text-ink-muted">{text}</p></div>)}</div></Container></section>;
}

function FAQ() {
  const [active, setActive] = useState<number | null>(0);
  return <section id="faq"><Container className="py-20 sm:py-28"><div className="mx-auto max-w-3xl"><div className="text-center"><p className="eyebrow">Questions, answered</p><h2 className="mt-4 font-serif text-4xl tracking-tight sm:text-5xl">Before you begin.</h2></div><div className="mt-12 divide-y divide-line border-y border-line">{faqs.map(([question,answer],i) => <div key={question}><button className="flex w-full items-center justify-between gap-6 py-5 text-left font-semibold text-ink" onClick={() => setActive(active === i ? null : i)} aria-expanded={active === i}>{question}<ChevronDown className={`h-4 w-4 shrink-0 text-ink-muted transition-transform ${active === i ? "rotate-180" : ""}`} /></button>{active === i && <p className="max-w-2xl pb-5 pr-10 text-sm leading-6 text-ink-muted">{answer}</p>}</div>)}</div></div></Container></section>;
}

function Footer() {
  return <footer className="bg-deep text-mint">
    <Container id="final-cta" className="border-b border-mint/15 py-20 text-center sm:py-28">
      <p className="eyebrow text-sage">Make the next question count</p>
      <h2 className="mx-auto mt-4 max-w-2xl font-serif text-4xl leading-tight tracking-tight sm:text-6xl">Your next literature review starts with one question.</h2>
      <Link href="/app" className="button-primary mt-9 px-6 py-3.5">Open App <ArrowRight className="h-4 w-4" /></Link>
    </Container>
    <Container className="grid gap-12 py-12 lg:grid-cols-[1.5fr_1fr_1fr_1fr]">
      <div><LogoLink variant="light" size="footer" /><p className="mt-4 max-w-xs text-sm leading-6 text-mint/60">A calmer, more credible way to move through research.</p></div>
      {[["Product","Features","How it works","Open app"],["Company","About Sykra","Contact","Careers"],["Legal","Privacy","Terms","Security"]].map(([heading,...links]) => <div key={heading}><h3 className="text-xs font-semibold uppercase tracking-widest text-sage">{heading}</h3><div className="mt-4 space-y-3 text-sm text-mint/60">{links.map(link => <a href={link === "Open app" ? "/app" : "#"} key={link} className="block hover:text-mint">{link}</a>)}</div></div>)}
    </Container>
    <Container className="flex flex-col gap-3 border-t border-mint/15 py-5 text-xs text-mint/40 sm:flex-row sm:justify-between">
      <span>© 2026 Sykra Research. All rights reserved.</span><span>Built for evidence-led work.</span>
    </Container>
  </footer>;
}

export default function LandingPage() {
  return <main><Navbar /><Hero /><SocialProof /><Problem /><Solution /><HowItWorks /><FAQ /><Footer /></main>;
}
