import GradientChatInput from './ui/gradient-chat-input';

export function GradientChatInputDemo() {
  return (
    <div className="relative flex h-[600px] w-full items-center justify-center overflow-hidden p-8">
      <GradientChatInput
        placeholder="Send Message"
        autoReply="Got it — looking into that now ✨"
        onSend={(message) => console.log('sent:', message)}
      />
    </div>
  );
}
