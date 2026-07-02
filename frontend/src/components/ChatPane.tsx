import { useCallback } from 'react';
import { AIChatDialogue, AIChatInput, Avatar, Radio, RadioGroup, Select } from '@douyinfe/semi-ui';
import type {
  RoleConfig,
  DialogueContentItemRendererMap,
  RenderAvatarProps,
  RenderActionProps,
} from '@douyinfe/semi-ui/lib/es/aiChatDialogue';
import type {
  Step,
  Message,
} from '@douyinfe/semi-foundation/lib/es/aiChatDialogue/foundation';
import type { MessageContent } from '@douyinfe/semi-foundation/lib/es/aiChatInput/interface';
import type { ChatMessage } from '../lib/types';
import { IMAGE_SIZES, IMAGE_STYLES, type Mode } from '../lib/types';

interface Props {
  chats: ChatMessage[];
  generating: boolean;
  mode: Mode;
  onModeChange: (m: Mode) => void;
  imageSize: string;
  onImageSizeChange: (v: string) => void;
  imageStyle: string;
  onImageStyleChange: (v: string) => void;
  onMessageSend: (payload: MessageContent) => void;
  onMessageDelete: (message: ChatMessage) => void;
  onChatsChange: (chats: ChatMessage[]) => void;
  onStopGenerate: () => void;
}

// roleConfig.avatar 走 Semi 内置渲染时会被当成图片 URL；
// 我们改用 renderDialogueAvatar 拿 role.avatar 作为 children（emoji / 文字），
// 只有当值明显是 http(s) 或 data:image URL 时才作为 src 走图片头像。
const roleConfig: RoleConfig = {
  user: { name: '你', avatar: '🙂', color: 'orange' },
  assistant: { name: '智能助手', avatar: '🤖', color: 'light-blue' },
};

function isImageSrc(v: unknown): v is string {
  return (
    typeof v === 'string' &&
    (v.startsWith('http://') ||
      v.startsWith('https://') ||
      v.startsWith('data:image/') ||
      v.startsWith('/'))
  );
}

/**
 * 自定义 content item 渲染：
 * - `steps`：不在 AIChatDialogue 默认渲染表里，交给官方 <AIChatDialogue.Step /> 组件。
 * - reasoning / message / function_call / custom_tool_call 走内置渲染，无需自定义。
 */
const contentItemRenderers: DialogueContentItemRendererMap = {
  steps: (item: unknown) => {
    const it = item as { steps?: Step[] };
    return <AIChatDialogue.Step steps={it.steps || []} />;
  },
};

/** 自定义头像：emoji / 文字走 children，URL 走 src。 */
function renderDialogueAvatar(props: RenderAvatarProps) {
  const role = props.role || {};
  const avatar = role.avatar as unknown;
  const color = (role.color as
    | 'orange'
    | 'light-blue'
    | 'green'
    | 'purple'
    | undefined) || 'grey';
  if (isImageSrc(avatar)) {
    return <Avatar size="extra-small" src={avatar} alt={role.name} />;
  }
  return (
    <Avatar size="extra-small" color={color}>
      {(avatar as string) || role.name?.[0] || '?'}
    </Avatar>
  );
}

/**
 * 自定义底部动作条：只保留复制、重试、更多（内含删除），
 * 移除 Semi 默认的 分享 / 点赞 / 点踩 / 编辑。
 */
function renderDialogueAction(props: RenderActionProps) {
  const { defaultActionsObj, className } = props;
  const nodes = [
    defaultActionsObj?.copyNode,
    defaultActionsObj?.resetNode,
    defaultActionsObj?.moreNode,
  ].filter(Boolean);
  return <div className={className}>{nodes}</div>;
}

/**
 * 主对话区：
 *   AIChatDialogue 负责历史消息 + 思考区(reasoning) + 工具步骤(steps) + Markdown/代码/图片全部渲染；
 *   AIChatInput 负责富文本输入 + 附件上传 + 停止按钮。
 *   顶部有一个「对话 / 画图」模式 toggle，画图模式下补两个下拉（尺寸 / 风格），
 *   并隐藏输入区的附件上传（生图端点不接受输入图）。
 */
export function ChatPane({
  chats,
  generating,
  mode,
  onModeChange,
  imageSize,
  onImageSizeChange,
  imageStyle,
  onImageStyleChange,
  onMessageSend,
  onMessageDelete,
  onChatsChange,
  onStopGenerate,
}: Props) {
  const handleChatsChange = useCallback(
    (cs?: Message[]) => onChatsChange((cs as ChatMessage[] | undefined) ?? []),
    [onChatsChange],
  );
  const isImage = mode === 'image';
  return (
    <>
      <div className="dialogue-scroll">
        <AIChatDialogue
          chats={chats}
          roleConfig={roleConfig}
          align="leftRight"
          mode="bubble"
          renderDialogueContentItem={contentItemRenderers}
          dialogueRenderConfig={{ renderDialogueAvatar, renderDialogueAction }}
          onChatsChange={handleChatsChange}
          onMessageDelete={(m) => onMessageDelete(m as ChatMessage)}
        />
      </div>
      <div className="mode-bar">
        <RadioGroup
          type="button"
          value={mode}
          onChange={(e) => onModeChange(e.target.value as Mode)}
        >
          <Radio value="chat">💬 对话</Radio>
          <Radio value="image">🎨 画图</Radio>
        </RadioGroup>
        {isImage && (
          <>
            <Select
              size="small"
              value={imageSize}
              onChange={(v) => onImageSizeChange(v as string)}
              style={{ width: 180 }}
              optionList={IMAGE_SIZES.map((s) => ({ label: s.label, value: s.value }))}
            />
            <Select
              size="small"
              value={imageStyle}
              onChange={(v) => onImageStyleChange(v as string)}
              style={{ width: 120 }}
              optionList={IMAGE_STYLES.map((s) => ({ label: s.label, value: s.value }))}
            />
          </>
        )}
      </div>
      <div className="input-wrap">
        <AIChatInput
          keepSkillAfterSend={false}
          placeholder={
            isImage ? '描述你想画的内容，例如：一只戴帽子的橘猫' : '输入消息，可粘贴图片链接。Enter 发送，Shift+Enter 换行'
          }
          generating={generating}
          onMessageSend={onMessageSend}
          onStopGenerate={onStopGenerate}
          uploadProps={
            isImage
              ? undefined // 画图模式不允许上传附件
              : {
                  action: '',
                  accept: 'image/*',
                  limit: 1,
                }
          }
        />
      </div>
    </>
  );
}
