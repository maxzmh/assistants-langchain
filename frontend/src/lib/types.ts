// 前端消息模型：直接复用 AIChatDialogue 的 Message；status/角色/ContentItem 结构与 Semi 一致。
import type { Message } from '@douyinfe/semi-foundation/lib/es/aiChatDialogue/foundation';

export type ChatMessage = Message & { remoteId?: string };

export const WELCOME_TEXT =
  '你好！我可以回答你的问题，也可以帮你分析图片。有什么想聊的？';

// Semi AIChatDialogue 里的段类型 / 状态常量，抽出来避免各处魔法字符串。
export const ITEM = {
  MESSAGE: 'message',
  OUTPUT_TEXT: 'output_text',
  REASONING: 'reasoning',
  STEPS: 'steps',
  INPUT_TEXT: 'input_text',
  INPUT_IMAGE: 'input_image',
} as const;

export const STATUS = {
  IN_PROGRESS: 'in_progress',
  COMPLETED: 'completed',
  FAILED: 'failed',
} as const;
