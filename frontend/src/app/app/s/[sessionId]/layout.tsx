import { SessionShell } from "@/components/AppShell";

export default async function SessionLayout({ params }: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = await params;
  return <SessionShell sessionId={sessionId} />;
}