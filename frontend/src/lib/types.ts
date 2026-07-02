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

// 输入模式：对话（走 /api/chat）或画图（走 /api/image/gen）。UI 中一个 toggle 切换。
export type Mode = 'chat' | 'image';

// 画图模式的画布尺寸档位。必须与 app/image/service.py:_ALLOWED_SIZES 保持一致。
// Seedream 4.x 硬要求：总像素 >= 3.69M，所以最小档也是 2048x2048。
export const IMAGE_SIZES = [
  { label: '方形 1:1 (2048×2048)', value: '2048x2048' },
  { label: '横屏 16:9 (2560×1440)', value: '2560x1440' },
  { label: '竖屏 9:16 (1440×2560)', value: '1440x2560' },
  { label: '横屏 3:2 (2400×1600)', value: '2400x1600' },
  { label: '竖屏 2:3 (1600×2400)', value: '1600x2400' },
] as const;

// 画图风格档位。后端以 style key 查前缀 prompt，然后拼进真实调用。
export const IMAGE_STYLES = [
  { label: '自然', value: 'natural' },
  { label: '通用高清', value: 'general' },
  { label: '动漫插画', value: 'anime' },
  { label: '写实摄影', value: 'photo' },
  { label: '水彩手绘', value: 'watercolor' },
] as const;
