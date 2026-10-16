"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { ClusterOut, ContradictionOut, FocusModeResponse } from "@/lib/types";

export function useResearchGraph(projectId: string) {
  const [clusters, setClusters] = useState<ClusterOut[] | null>(null);
  const [contradictions, setContradictions] = useState<ContradictionOut[]>([]);
  const [loadedFor, setLoadedFor] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const loading = refreshing || loadedFor !== projectId;

  const [focusLink, setFocusLink] = useState<string | null>(null);
  const [focusTitle, setFocusTitle] = useState<string | null>(null);
  const [focus, setFocus] = useState<FocusModeResponse | null>(null);
  const [focusLoading, setFocusLoading] = useState(false);
  const [focusError, setFocusError] = useState<string | null>(null);

  const fetchOverview = useCallback(
    async (isCancelled: () => boolean = () => false) => {
      try {
        const [clusterRes, contradictionRes] = await Promise.all([
          api.getClusters(projectId),
          api.getContradictions(projectId),
        ]);
        if (isCancelled()) return;
        setClusters(clusterRes.clusters);
        setContradictions(contradictionRes.contradictions);
        setError(null);
      } catch (e) {
        if (isCancelled()) return;
        setError(e instanceof ApiError ? e.message : "Could not load the research graph for this project.");
      } finally {
        if (!isCancelled()) setLoadedFor(projectId);
      }
    },
    [projectId]
  );

  useEffect(() => {
    let cancelled = false;
    void fetchOverview(() => cancelled);
    return () => { cancelled = true; };
  }, [fetchOverview]);

  async function loadOverview() {
    setRefreshing(true);
    try { await fetchOverview(); } finally { setRefreshing(false); }
  }

    async function openFocus(link: string, title: string) {
    setFocusLink(link);
    setFocusTitle(title);
    setFocus(null);
    setFocusError(null);
    setFocusLoading(true);
    try {
      const res = await api.getFocus(link);
      setFocus(res);
    } catch (e) {
      setFocusError(e instanceof ApiError ? e.message : "Could not load this paper's neighborhood.");
    } finally {
      setFocusLoading(false);
    }
  }

  function closeFocus() {
    setFocusLink(null);
    setFocus(null);
    setFocusError(null);
  }

  return {
    clusters,
    contradictions,
    loading,
    error,
    loadOverview,
    focusLink,
    focusTitle,
    focus,
    focusLoading,
    focusError,
    openFocus,
    closeFocus,
  };
}