import { AppShell } from "@/components/AppShell";

export default async function SessionPage({ params }: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = await params;
  return <AppShell initialSessionId={sessionId} />;
}
