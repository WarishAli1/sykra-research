"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { ClusterOut, ContradictionOut, FocusModeResponse } from "@/lib/types";

function overviewErrorMessage(e: unknown): string {
  return e instanceof ApiError
    ? e.message
    : "Could not load the research graph for this project.";
}

export function useResearchGraph(projectId: string, chatId?: string) {
  const [clusters, setClusters] = useState<ClusterOut[] | null>(null);
  const [contradictions, setContradictions] = useState<ContradictionOut[]>([]);
  const [loadedFor, setLoadedFor] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const viewKey = `${projectId}|${chatId ?? ""}`;
  const loading = refreshing || loadedFor !== viewKey;
  const [focusLink, setFocusLink] = useState<string | null>(null);
  const [focusTitle, setFocusTitle] = useState<string | null>(null);
  const [focus, setFocus] = useState<FocusModeResponse | null>(null);
  const [focusLoading, setFocusLoading] = useState(false);
  const [focusError, setFocusError] = useState<string | null>(null);

  const fetchOverviewData = useCallback(
    () =>
      Promise.all([
        api.getClusters(projectId, chatId),
        api.getContradictions(projectId),
      ]),
    [projectId, chatId]
  );

  useEffect(() => {
    let cancelled = false;
    fetchOverviewData()
      .then(([clusterRes, contradictionRes]) => {
        if (cancelled) return;
        setClusters(clusterRes.clusters);
        setContradictions(contradictionRes.contradictions);
        setError(null);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(overviewErrorMessage(e));
      })
      .finally(() => {
        setLoadedFor(viewKey)
      });
    return () => {
      cancelled = true;
    };
  }, [fetchOverviewData, viewKey]);

  async function loadOverview() {
    setRefreshing(true);
    try {
      const [clusterRes, contradictionRes] = await fetchOverviewData();
      setClusters(clusterRes.clusters);
      setContradictions(contradictionRes.contradictions);
      setError(null);
    } catch (e) {
      setError(overviewErrorMessage(e));
    } finally {
      setLoadedFor(viewKey);
      setRefreshing(false);
    }
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