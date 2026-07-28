import { motion, AnimatePresence } from "framer-motion";
import { ChevronDown, Search, Globe } from "lucide-react";
import { useState } from "react";

interface ResearchStepProps {
  title: string;
  icon: React.ElementType;
  status: "pending" | "active" | "completed";
  queries: string[];
  items: string[];
}

export function ResearchStep({ title, icon: Icon, status, queries, items }: ResearchStepProps) {
  const [sourcesExpanded, setSourcesExpanded] = useState(true);
  
  const isActive = status === "active";
  const isCompleted = status === "completed";

  return (
    <motion.div 
      className="relative"
      initial={{ opacity: 0, x: -10 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.4, ease: "easeOut" }}
    >
      <div className="absolute -left-6 top-0 flex items-center justify-center">
        <motion.div
          className={`flex h-3.5 w-3.5 items-center justify-center rounded-full border-2 bg-paper ${
            isActive ? "border-indigo" : isCompleted ? "border-gold bg-gold" : "border-line"
          }`}
          animate={isActive ? { scale: [1, 1.2, 1], borderColor: ["#4f46e5", "#818cf8", "#4f46e5"] } : { scale: 1 }}
          transition={{ repeat: isActive ? Infinity : 0, duration: 2, ease: "easeInOut" }}
        >
          {isCompleted && <div className="h-1.5 w-1.5 rounded-full bg-paper" />}
        </motion.div>
      </div>

      {/* Content */}
      <div className="pt-0.5">
        <div className="flex items-center gap-1.5 text-[12.5px] font-medium text-ink">
          <Icon
            className={`h-3.5 w-3.5 ${
              isActive ? "text-indigo animate-pulse" : isCompleted ? "text-ink-soft" : "text-ink-soft/50"
            }`}
          />
          <span className={status === "pending" ? "text-ink-soft/50" : "text-ink"}>
            {title}
          </span>
        </div>

        <AnimatePresence>
          {(queries.length > 0 || items.length > 0) && (
            <motion.div
              initial={{ opacity: 0, height: 0, marginTop: 0 }}
              animate={{ opacity: 1, height: "auto", marginTop: 8 }}
              exit={{ opacity: 0, height: 0, marginTop: 0 }}
              transition={{ duration: 0.3, ease: "easeInOut" }}
              className="overflow-hidden"
            >
              <div className="rounded-lg border border-line bg-paper-dim/50 p-3 space-y-3">
                {queries.map((query, idx) => (
                  <motion.div
                    key={idx}
                    initial={{ opacity: 0, y: 5 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: idx * 0.1 }}
                    className="flex items-center gap-1.5 rounded-md bg-paper px-2.5 py-1.5 text-[11.5px] text-ink-soft"
                  >
                    <Search className="h-3 w-3 shrink-0 text-ink-soft/70" />
                    <span className="truncate">{query}</span>
                  </motion.div>
                ))}

                {items.length > 0 && (
                  <div>
                    <button
                      onClick={() => setSourcesExpanded((v) => !v)}
                      className="flex w-full items-center justify-between text-[11.5px] font-medium text-ink-soft hover:text-ink transition-colors focus:outline-none"
                      aria-expanded={sourcesExpanded}
                    >
                      <span>Reviewing sources ({items.length})</span>
                      <motion.div
                        animate={{ rotate: sourcesExpanded ? 180 : 0 }}
                        transition={{ duration: 0.2 }}
                      >
                        <ChevronDown className="h-3 w-3" />
                      </motion.div>
                    </button>

                    <AnimatePresence>
                      {sourcesExpanded && (
                        <motion.div
                          initial={{ opacity: 0, height: 0 }}
                          animate={{ opacity: 1, height: "auto" }}
                          exit={{ opacity: 0, height: 0 }}
                          transition={{ duration: 0.25, ease: "easeInOut" }}
                          className="overflow-hidden"
                        >
                          <div className="mt-2 space-y-1">
                            {items.map((item, idx) => (
                              <motion.div
                                key={idx}
                                initial={{ opacity: 0, x: -5 }}
                                animate={{ opacity: 1, x: 0 }}
                                transition={{ delay: idx * 0.05 }}
                                className="flex items-center gap-2 rounded-md bg-paper px-2.5 py-1.5 text-[11.5px] text-ink"
                              >
                                <Globe className="h-3 w-3 shrink-0 text-gold" />
                                <span className="truncate">{item}</span>
                              </motion.div>
                            ))}
                          </div>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </div>
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  );
}