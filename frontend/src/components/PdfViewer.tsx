"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import { Minus, PanelLeft, Plus, X } from "lucide-react";
import "react-pdf/dist/Page/TextLayer.css";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "./PdfViewer.css";

pdfjs.GlobalWorkerOptions.workerSrc = `https://unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`;

interface PdfViewerProps {
  url: string;
  onClose: () => void;
}

export function PdfViewer({ url, onClose }: PdfViewerProps) {
  const [numPages, setNumPages] = useState(0);
  const [currentPage, setCurrentPage] = useState(1);
  const [scale, setScale] = useState(1);
  const [showSidebar, setShowSidebar] = useState(false);
  const [loading, setLoading] = useState(true);
  const [pageWidth, setPageWidth] = useState(800);
  const [loadError, setLoadError] = useState<string | null>(null);
  const viewerRef = useRef<HTMLDivElement>(null);
  const pageRefs = useRef<(HTMLDivElement | null)[]>([]);

  const filename = useMemo(() => {
    try {
      const u = new URL(url, window.location.origin);
      const last = u.pathname.split("/").filter(Boolean).pop() ?? "";
      return decodeURIComponent(last) || "document.pdf";
    } catch {
      return decodeURIComponent(url.split("/").pop() || "document.pdf");
    }
  }, [url]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    const el = viewerRef.current;
    if (!el) return;
    const compute = () => {
      const w = el.clientWidth;
      setPageWidth(Math.max(320, Math.min(w - 80, 850)));
    };
    compute();
    const ro = new ResizeObserver(compute);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    if (!numPages) return;
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          const page = Number(entry.target.getAttribute("data-page"));
          if (page) setCurrentPage(page);
        });
      },
      { root: viewerRef.current, threshold: 0.6 }
    );
    pageRefs.current.forEach((page) => {
      if (page) observer.observe(page);
    });
    return () => observer.disconnect();
  }, [numPages]);

  const validUrl = /^https?:\/\//i.test(url);

  return (
    <div className="flex h-full w-full min-w-0">
      <div className="pdf-dock flex h-full w-full flex-col overflow-hidden">
        <div className="pdf-header">
          <div className="flex min-w-0 items-center gap-3">
            <span className="pdf-title" title={filename}>
              {filename}
            </span>
          </div>
          <div className="flex shrink-0 items-center gap-1.5">
            <button
              className="toolbar-btn"
              title="Toggle thumbnails"
              aria-label="Toggle thumbnails"
              onClick={() => setShowSidebar((v) => !v)}
            >
              <PanelLeft size={18} />
            </button>
            <div className="page-count">
              <span className="page-current">{currentPage}</span> / {numPages}
            </div>
            <button
              className="toolbar-btn"
              disabled={scale <= 0.6}
              onClick={() => setScale((s) => Math.max(0.6, s - 0.1))}
            >
              <Minus size={18} />
            </button>
            <span className="zoom-label">{Math.round(scale * 100)}%</span>
            <button
              className="toolbar-btn"
              disabled={scale >= 2.5}
              onClick={() => setScale((s) => Math.min(2.5, s + 0.1))}
            >
              <Plus size={18} />
            </button>
            <span className="header-divider" />
            <button className="toolbar-btn" onClick={onClose} aria-label="Close PDF">
              <X size={18} />
            </button>
          </div>
        </div>

        {/* Body */}
        {!validUrl || loadError ? (
          <div className="flex flex-1 items-center justify-center p-8 text-center">
            <p className="text-[13.5px] text-white/70">{loadError ?? "No PDF to display."}</p>
          </div>
        ) : (
          <div className="flex flex-1 overflow-hidden">
            {showSidebar && (
              <div className="sidebar">
                <Document
                  file={url}
                  loading={null}
                  onLoadError={(err) => console.error("PDF sidebar load error:", err)}
                >
                  {Array.from({ length: numPages }, (_, index) => (
                    <div
                      key={index}
                      className={`thumbnail-page ${currentPage === index + 1 ? "thumbnail-active" : ""}`}
                      onClick={() =>
                        pageRefs.current[index]?.scrollIntoView({ behavior: "smooth", block: "start" })
                      }
                    >
                      <div className="flex justify-center">
                        <Page
                          pageNumber={index + 1}
                          width={90}
                          renderTextLayer={false}
                          renderAnnotationLayer={false}
                        />
                      </div>
                      <p style={{ marginTop: 8, fontSize: 11, textAlign: "center" }}>{index + 1}</p>
                    </div>
                  ))}
                </Document>
              </div>
            )}
            <div ref={viewerRef} className="pdf-viewer">
              {loading && (
                <div className="flex h-full items-center justify-center">
                  <span style={{ color: "rgba(255,255,255,0.85)", fontWeight: 600 }}>Loading PDF...</span>
                </div>
              )}
              <Document
                file={url}
                loading={null}
                onLoadSuccess={({ numPages }) => {
                  setNumPages(numPages);
                  setLoading(false);
                }}
                onLoadError={(err) => {
                  console.error("PDF load error:", err);
                  setLoading(false);
                  setLoadError("Couldn't load this PDF. It may be missing, moved, or corrupted.");
                }}
              >
                {Array.from({ length: numPages }, (_, index) => (
                  <div
                    key={index}
                    ref={(el) => {
                      pageRefs.current[index] = el;
                    }}
                    data-page={index + 1}
                    className="flex justify-center mb-10"
                  >
                    <div className="pdf-page-wrapper">
                      <Page
                        pageNumber={index + 1}
                        width={pageWidth * scale}
                        renderTextLayer
                        renderAnnotationLayer
                      />
                    </div>
                  </div>
                ))}
              </Document>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}