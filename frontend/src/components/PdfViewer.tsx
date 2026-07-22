"use client";

import { useEffect, useRef, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import { Minus, PanelLeft, Plus, X } from "lucide-react";

import "react-pdf/dist/Page/TextLayer.css";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "./PdfViewer.css";

pdfjs.GlobalWorkerOptions.workerSrc = `//unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`;

interface PdfViewerProps {
  url: string;
  onClose: () => void;
}

export function PdfViewer({
  url,
  onClose,
}: PdfViewerProps) {
  const [numPages, setNumPages] = useState(0);
  const [currentPage, setCurrentPage] = useState(1);
  const [scale, setScale] = useState(1);
  const [showSidebar, setShowSidebar] = useState(true);
  const [loading, setLoading] = useState(true);
  const [pageWidth, setPageWidth] = useState(800);

  const viewerRef = useRef<HTMLDivElement>(null);
  const pageRefs = useRef<(HTMLDivElement | null)[]>([]);

  useEffect(() => {
    const updateWidth = () => {
      if (!viewerRef.current) return;

      const width = viewerRef.current.clientWidth;

      setPageWidth(Math.min(width - 80, 850));
    };

    updateWidth();

    window.addEventListener("resize", updateWidth);

    return () => window.removeEventListener("resize", updateWidth);
  }, []);

  useEffect(() => {
    if (!numPages) return;

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;

          const page = Number(
            entry.target.getAttribute("data-page")
          );

          if (page) setCurrentPage(page);
        });
      },
      {
        root: viewerRef.current,
        threshold: 0.6,
      }
    );

    pageRefs.current.forEach((page) => {
      if (page) observer.observe(page);
    });

    return () => observer.disconnect();
  }, [numPages]);
  return (
  <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-6">

    <div className="w-[94vw] h-[94vh] bg-[#FAFBFC] rounded-xl shadow-2xl overflow-hidden flex flex-col">

      {/* Header */}

      <div className="pdf-header">

        <div className="flex items-center gap-2">

          <button
            className="toolbar-btn"
            onClick={() => setShowSidebar((v) => !v)}
          >
            <PanelLeft size={18} />
          </button>

          <div className="page-count">
            {currentPage} / {numPages}
          </div>

          <button
            className="toolbar-btn"
            disabled={scale <= 0.6}
            onClick={() =>
              setScale((s) => Math.max(0.6, s - 0.1))
            }
          >
            <Minus size={18} />
          </button>

          <span
            style={{
              color: "white",
              width: 55,
              textAlign: "center",
              fontSize: 13,
              fontWeight: 500,
            }}
          >
            {Math.round(scale * 100)}%
          </span>

          <button
            className="toolbar-btn"
            disabled={scale >= 2.5}
            onClick={() =>
              setScale((s) => Math.min(2.5, s + 0.1))
            }
          >
            <Plus size={18} />
          </button>

        </div>

        <button
          className="toolbar-btn"
          onClick={onClose}
        >
          <X size={18} />
        </button>

      </div>

      {/* Body */}

      <div className="flex flex-1 overflow-hidden">

        {showSidebar && (

          <div className="sidebar">

            <Document
              file={url}
              loading={null}
            >

              {Array.from(
                { length: numPages },
                (_, index) => (

                  <div
                    key={index}
                    className={`thumbnail-page ${
                      currentPage === index + 1
                        ? "thumbnail-active"
                        : ""
                    }`}
                    onClick={() =>
                      pageRefs.current[index]?.scrollIntoView({
                        behavior: "smooth",
                        block: "start",
                      })
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

                    <p
                      style={{
                        marginTop: 8,
                        fontSize: 11,
                        textAlign: "center",
                        color: "#64748b",
                      }}
                    >
                      {index + 1}
                    </p>

                  </div>

                )
              )}

            </Document>

          </div>

        )}

        <div
          ref={viewerRef}
          className="pdf-viewer"
        >

          {loading && (

            <div className="flex h-full items-center justify-center">

              <span
                style={{
                  color: "#1F3A5F",
                  fontWeight: 600,
                }}
              >
                Loading PDF...
              </span>

            </div>

          )}

          <Document
            file={url}
            loading={null}
            onLoadSuccess={({ numPages }) => {
              setNumPages(numPages);
              setLoading(false);
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

    </div>

  </div>
);
}