import { AppShell } from "@/components/AppShell";

export default async function SessionChatPage({ params }: { params: Promise<{ sessionId: string; chatId: string }> }) {
  const { sessionId, chatId } = await params;
  return <AppShell initialSessionId={sessionId} initialChatId={chatId} />;
}
