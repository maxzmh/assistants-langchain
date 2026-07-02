import { useCallback, useEffect, useRef, useState } from 'react';
import { Toast } from '@douyinfe/semi-ui';
import type {
  Attachment,
  Content as InputContent,
  MessageContent,
} from '@douyinfe/semi-foundation/lib/es/aiChatInput/interface';
import type {
  ContentItem,
  Reasoning,
  Step,
} from '@douyinfe/semi-foundation/lib/es/aiChatDialogue/foundation';
import { Sidebar } from './components/Sidebar';
import { ChatPane } from './components/ChatPane';
import {
  createSession,
  deleteMessage as apiDeleteMessage,
  deleteSession as apiDeleteSession,
  generateImage,
  getHistory,
  listSessions,
  newSessionId,
  streamChat,
  type ChatEvent,
  type SessionItem,
} from './lib/api';
import {
  IMAGE_SIZES,
  IMAGE_STYLES,
  ITEM,
  STATUS,
  WELCOME_TEXT,
  type ChatMessage,
  type Mode,
} from './lib/types';

/** 本地 id 生成器：Message.id / ContentItem.id 都需要稳定唯一。 */
let _mid = 0;
const nextId = (prefix = 'm') =>
  prefix + Date.now().toString(36) + '-' + ++_mid;

/** 助手欢迎语。 */
function welcomeMessage(): ChatMessage {
  return {
    id: nextId(),
    role: 'assistant',
    content: [
      {
        id: nextId('c'),
        type: ITEM.MESSAGE,
        content: [{ type: ITEM.OUTPUT_TEXT, text: WELCOME_TEXT }],
      } as ContentItem,
    ],
    status: STATUS.COMPLETED,
    createdAt: Date.now(),
  };
}

/** 用 tiptap content 里的 text 段拼出发送给后端的原文；顺带把 image_url 抽成图片段。 */
function extractRawText(inputContents?: InputContent[]): string {
  if (!inputContents) return '';
  const parts: string[] = [];
  for (const c of inputContents) {
    if (typeof c.text === 'string') parts.push(c.text);
  }
  return parts.join('').trim();
}

/** history 回显：把后端存的一条消息映射成 Semi ContentItem[]。
 *
 * 关键点：AIChatDialogue 顶层 builtinRenderers 只识别
 *   message / reasoning / function_call / custom_tool_call，
 * 而 input_text / input_image 是"消息内的段"，必须嵌套在一个 message 段里
 * 才会被内部 renderMessage 消费。
 */
function historyToContent(
  text: string,
  imageUrl: string | null,
  role: 'user' | 'assistant',
): ContentItem[] {
  if (role === 'assistant') {
    // 助手历史：如果这条消息带图（画图模式产物），把图片作为 markdown 语法拼进
    // 正文，Semi 内置 markdown 渲染会显示图。这样不用赌 image_url 段在 assistant
    // 侧的兼容性，也让「文本 + 图」的顺序稳定。
    const md = imageUrl ? `${text ? text + '\n\n' : ''}![](${imageUrl})` : text;
    return md
      ? [
          {
            id: nextId('c'),
            type: ITEM.MESSAGE,
            content: [{ type: ITEM.OUTPUT_TEXT, text: md }],
          } as ContentItem,
        ]
      : [];
  }
  // 用户历史：把图 + 文本都装进一个 message 段里
  const inner: Array<{ type: string; text?: string; image_url?: string }> = [];
  if (imageUrl) inner.push({ type: ITEM.INPUT_IMAGE, image_url: imageUrl });
  if (text) inner.push({ type: ITEM.INPUT_TEXT, text });
  if (!inner.length) return [];
  return [
    {
      id: nextId('c'),
      type: ITEM.MESSAGE,
      content: inner,
    } as ContentItem,
  ];
}

/** 构造用户消息 content：本地文件用 blob URL 展示。 */
function buildUserContent(
  text: string,
  attachments: Attachment[] | undefined,
): ContentItem[] {
  const inner: Array<{ type: string; text?: string; image_url?: string }> = [];
  const firstImg = attachments?.find(
    (a) => (a.fileInstance as File | undefined)?.type?.startsWith('image/'),
  );
  if (firstImg?.fileInstance) {
    inner.push({
      type: ITEM.INPUT_IMAGE,
      image_url: URL.createObjectURL(firstImg.fileInstance as File),
    });
  }
  if (text) inner.push({ type: ITEM.INPUT_TEXT, text });
  if (!inner.length) return [];
  return [
    {
      id: nextId('c'),
      type: ITEM.MESSAGE,
      content: inner,
    } as ContentItem,
  ];
}

/**
 * 从助手 content[] 里取某一段（reasoning / steps），没有就 append 一段并返回引用。
 * 返回的对象是新 message 里的 item —— 调用点里 map 时把它塞到新 content 数组中。
 */
function ensureItem<T extends ContentItem>(
  items: ContentItem[],
  type: string,
  factory: () => T,
): { items: ContentItem[]; item: T } {
  const idx = items.findIndex((i) => i.type === type);
  if (idx >= 0) {
    const cloned = items.slice();
    const clonedItem = { ...cloned[idx] } as T;
    cloned[idx] = clonedItem;
    return { items: cloned, item: clonedItem };
  }
  const item = factory();
  return { items: [...items, item], item };
}

export default function App() {
  const [sessions, setSessions] = useState<SessionItem[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [chats, setChats] = useState<ChatMessage[]>([]);
  const [generating, setGenerating] = useState(false);
  // 画图模式状态：mode + 尺寸 + 风格。默认第一档尺寸 / 自然风格。
  const [mode, setMode] = useState<Mode>('chat');
  const [imageSize, setImageSize] = useState<string>(IMAGE_SIZES[0].value);
  const [imageStyle, setImageStyle] = useState<string>(IMAGE_STYLES[0].value);
  const dirtyRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);

  const patchAssistant = useCallback(
    (id: string, patch: (m: ChatMessage) => ChatMessage) => {
      setChats((ms) => ms.map((m) => (m.id === id ? patch(m) : m)));
    },
    [],
  );

  const refreshSessions = useCallback(async () => {
    try {
      const list = await listSessions();
      setSessions(list);
      return list;
    } catch {
      Toast.error('加载会话列表失败');
      return [];
    }
  }, []);

  const openSession = useCallback(async (id: string) => {
    setActiveId(id);
    dirtyRef.current = true;
    try {
      const msgs = await getHistory(id);
      if (!msgs.length) {
        setChats([welcomeMessage()]);
      } else {
        setChats(
          msgs.map<ChatMessage>((m) => {
            const role = m.role === 'user' ? 'user' : 'assistant';
            return {
              id: nextId(),
              remoteId: m.id,
              role,
              content: historyToContent(m.text, m.image ?? null, role),
              status: STATUS.COMPLETED,
              createdAt: Date.now(),
            };
          }),
        );
      }
    } catch {
      Toast.error('加载消息失败');
    }
  }, []);

  const handleNew = useCallback(async () => {
    if (activeId && !dirtyRef.current) {
      setChats([welcomeMessage()]);
      await refreshSessions();
      return;
    }
    const id = newSessionId();
    dirtyRef.current = false;
    try {
      await createSession(id);
    } catch {
      // 首条消息发出去时后端 touch 会兜底
    }
    setActiveId(id);
    setChats([welcomeMessage()]);
    await refreshSessions();
  }, [activeId, refreshSessions]);

  const handleDeleteSession = useCallback(
    async (id: string) => {
      try {
        await apiDeleteSession(id);
      } catch {
        Toast.error('删除失败');
        return;
      }
      if (id === activeId) {
        await handleNew();
      } else {
        await refreshSessions();
      }
    },
    [activeId, handleNew, refreshSessions],
  );

  const handleDeleteMessage = useCallback(
    async (msg: ChatMessage) => {
      if (!msg.remoteId || !activeId) {
        setChats((ms) => ms.filter((m) => m.id !== msg.id));
        return;
      }
      try {
        const ok = await apiDeleteMessage(activeId, msg.remoteId);
        if (ok) setChats((ms) => ms.filter((m) => m.id !== msg.id));
      } catch {
        Toast.error('删除失败');
      }
    },
    [activeId],
  );

  const handleStop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const handleSend = useCallback(
    async (payload: MessageContent) => {
      if (!activeId) return;
      const raw = extractRawText(payload.inputContents);
      const attachments = payload.attachments || [];
      const firstFile =
        (attachments.find((a) => !!a.fileInstance)?.fileInstance as
          | File
          | undefined) || null;
      if (!raw && !firstFile) return;

      // —— 画图模式：走独立生图端点，非流式；不进 checkpoint，只写 message_store ——
      if (mode === 'image') {
        if (!raw) {
          Toast.warning('请输入画图提示词');
          return;
        }
        const userId = nextId();
        const botId = nextId();
        const now = Date.now();
        // 用户气泡先展示 [画图] prompt，助手气泡先显示 loading
        setChats((ms) => [
          ...ms,
          {
            id: userId,
            role: 'user',
            content: buildUserContent(`[画图] ${raw}`, []),
            status: STATUS.COMPLETED,
            createdAt: now,
          },
          {
            id: botId,
            role: 'assistant',
            content: [],
            status: STATUS.IN_PROGRESS,
            createdAt: now,
          },
        ]);
        const wasFirst = !dirtyRef.current;
        dirtyRef.current = true;
        setGenerating(true);
        try {
          const res = await generateImage({
            sessionId: activeId,
            prompt: raw,
            size: imageSize,
            style: imageStyle,
          });
          // 助手气泡替换为「prompt + markdown 图」+ 挂 remoteId
          setChats((ms) =>
            ms.map((m) => {
              if (m.id === userId) return { ...m, remoteId: res.user_id };
              if (m.id === botId)
                return {
                  ...m,
                  remoteId: res.ai_id,
                  status: STATUS.COMPLETED,
                  content: historyToContent(raw, res.image_url, 'assistant'),
                };
              return m;
            }),
          );
        } catch (err: unknown) {
          const msg = err instanceof Error ? err.message : String(err);
          Toast.error('生图失败：' + msg);
          patchAssistant(botId, (m) => ({
            ...m,
            status: STATUS.FAILED,
            content: [
              {
                id: nextId('c'),
                type: ITEM.MESSAGE,
                content: [{ type: ITEM.OUTPUT_TEXT, text: `[生图失败] ${msg}` }],
              } as ContentItem,
            ],
          }));
        } finally {
          setGenerating(false);
          if (wasFirst) refreshSessions();
        }
        return;
      }

      const userId = nextId();
      const botId = nextId();
      const now = Date.now();
      setChats((ms) => [
        ...ms,
        {
          id: userId,
          role: 'user',
          content: buildUserContent(raw, attachments),
          status: STATUS.COMPLETED,
          createdAt: now,
        },
        {
          id: botId,
          role: 'assistant',
          // 初始为空 —— 让 reasoning / steps 段自然排在前面，
          // message 段等第一次 delta 到达时再追加到末尾。
          // in_progress + 空 content 时 AIChatDialogue 会显示 loading 三点占位。
          content: [],
          status: STATUS.IN_PROGRESS,
          createdAt: now,
        },
      ]);

      const wasFirst = !dirtyRef.current;
      dirtyRef.current = true;
      setGenerating(true);

      // 累积字符串 & 工具索引本地维护，避免每帧读旧状态。
      let acc = '';
      let reasoningAcc = '';
      const toolIndex = new Map<string, number>(); // tool run_id → steps.actions[] 下标

      const appendReasoningDelta = (delta: string) => {
        reasoningAcc += delta;
        patchAssistant(botId, (m) => {
          const { items, item } = ensureItem<Reasoning>(
            (m.content as ContentItem[]) || [],
            ITEM.REASONING,
            () => ({
              id: nextId('c'),
              type: ITEM.REASONING,
              status: STATUS.IN_PROGRESS,
              content: [{ type: 'text', text: '' }],
            }),
          );
          item.status = STATUS.IN_PROGRESS;
          item.content = [{ type: 'text', text: reasoningAcc }];
          return { ...m, content: items };
        });
      };

      const finishReasoning = () => {
        if (!reasoningAcc) return;
        patchAssistant(botId, (m) => {
          const content = ((m.content as ContentItem[]) || []).map((it) =>
            it.type === ITEM.REASONING
              ? ({ ...it, status: STATUS.COMPLETED } as Reasoning)
              : it,
          );
          return { ...m, content };
        });
      };

      const upsertToolStep = (runId: string, patch: (a: Step['actions'] extends (infer A)[] | undefined ? A : never) => void) => {
        patchAssistant(botId, (m) => {
          const items = ((m.content as ContentItem[]) || []).slice();
          let idx = items.findIndex((i) => i.type === ITEM.STEPS);
          let stepItem: (ContentItem & { steps?: Step[] }) | null =
            idx >= 0 ? ({ ...(items[idx] as ContentItem & { steps?: Step[] }) }) : null;
          if (!stepItem) {
            stepItem = {
              id: nextId('c'),
              type: ITEM.STEPS,
              steps: [
                {
                  type: 'function_call',
                  status: STATUS.IN_PROGRESS,
                  summary: '工具调用',
                  actions: [],
                },
              ],
            };
            idx = items.length;
            items.push(stepItem);
          } else {
            stepItem = { ...stepItem };
            stepItem.steps = (stepItem.steps || []).slice();
            if (!stepItem.steps.length) {
              stepItem.steps.push({
                type: 'function_call',
                status: STATUS.IN_PROGRESS,
                summary: '工具调用',
                actions: [],
              });
            } else {
              stepItem.steps[0] = { ...stepItem.steps[0] };
            }
            items[idx] = stepItem;
          }
          const step = stepItem.steps![0];
          step.actions = (step.actions || []).slice();
          let aidx = toolIndex.get(runId);
          if (aidx === undefined) {
            aidx = step.actions.length;
            toolIndex.set(runId, aidx);
            step.actions.push({});
          } else {
            step.actions[aidx] = { ...step.actions[aidx] };
          }
          patch(step.actions[aidx] as never);
          // 若全部工具动作都 completed，把 step.status 也标记 completed
          if (step.actions.every((a) => a.status === STATUS.COMPLETED)) {
            step.status = STATUS.COMPLETED;
          } else {
            step.status = STATUS.IN_PROGRESS;
          }
          return { ...m, content: items };
        });
      };

      const appendMainDelta = (delta: string) => {
        acc += delta;
        patchAssistant(botId, (m) => {
          const items = ((m.content as ContentItem[]) || []).slice();
          const idx = items.findIndex((i) => i.type === ITEM.MESSAGE);
          if (idx < 0) {
            items.push({
              id: nextId('c'),
              type: ITEM.MESSAGE,
              content: [{ type: ITEM.OUTPUT_TEXT, text: acc }],
            } as ContentItem);
          } else {
            items[idx] = {
              ...items[idx],
              content: [{ type: ITEM.OUTPUT_TEXT, text: acc }],
            } as ContentItem;
          }
          return { ...m, content: items };
        });
      };

      const onEvent = (evt: ChatEvent) => {
        if (evt.type === 'reasoning' && evt.delta) {
          appendReasoningDelta(evt.delta);
        } else if (evt.type === 'tool_start') {
          upsertToolStep(evt.id, (a) => {
            const anyA = a as Record<string, unknown>;
            anyA.status = STATUS.IN_PROGRESS;
            anyA.summary = `🔧 ${evt.name || 'tool'}`;
            anyA.description = fmtToolInput(evt.input);
          });
        } else if (evt.type === 'tool_end') {
          upsertToolStep(evt.id, (a) => {
            const anyA = a as Record<string, unknown>;
            anyA.status = STATUS.COMPLETED;
            const out = fmtToolOutput(evt.output);
            if (out) anyA.description = out;
          });
        } else if (evt.type === 'ids') {
          if (evt.user_id) {
            setChats((ms) =>
              ms.map((m) =>
                m.id === userId ? { ...m, remoteId: evt.user_id } : m,
              ),
            );
          }
          if (evt.ai_id) {
            patchAssistant(botId, (m) => ({ ...m, remoteId: evt.ai_id }));
          }
        } else if (evt.type === 'error') {
          acc += '\n\n[出错了：' + evt.message + ']';
          appendMainDelta(''); // 触发一次 setChats 让主段更新
          patchAssistant(botId, (m) => ({ ...m, status: STATUS.FAILED }));
        } else {
          const delta =
            evt.type === 'delta' ? evt.text : (evt as { delta?: string }).delta;
          if (delta) appendMainDelta(delta);
        }
      };

      const ac = new AbortController();
      abortRef.current = ac;
      try {
        await streamChat({
          message: raw,
          sessionId: activeId,
          image: firstFile,
          onEvent,
          signal: ac.signal,
        });
      } catch (err: unknown) {
        if (!(err instanceof DOMException && err.name === 'AbortError')) {
          const msg = err instanceof Error ? err.message : String(err);
          acc += '\n\n[出错了：' + msg + ']';
          appendMainDelta('');
          patchAssistant(botId, (m) => ({ ...m, status: STATUS.FAILED }));
        }
      } finally {
        abortRef.current = null;
        finishReasoning();
        patchAssistant(botId, (m) => ({
          ...m,
          status:
            m.status === STATUS.FAILED ? STATUS.FAILED : STATUS.COMPLETED,
        }));
        setGenerating(false);
        if (wasFirst) refreshSessions();
      }
    },
    [activeId, mode, imageSize, imageStyle, patchAssistant, refreshSessions],
  );

  useEffect(() => {
    (async () => {
      const list = await refreshSessions();
      if (list.length) {
        await openSession(list[0].session_id);
      } else {
        await handleNew();
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="app">
      <Sidebar
        sessions={sessions}
        activeId={activeId}
        onNew={handleNew}
        onSwitch={openSession}
        onDelete={handleDeleteSession}
      />
      <div className="main">
        <ChatPane
          chats={chats}
          generating={generating}
          mode={mode}
          onModeChange={setMode}
          imageSize={imageSize}
          onImageSizeChange={setImageSize}
          imageStyle={imageStyle}
          onImageStyleChange={setImageStyle}
          onMessageSend={handleSend}
          onMessageDelete={handleDeleteMessage}
          onChatsChange={setChats}
          onStopGenerate={handleStop}
        />
      </div>
    </div>
  );
}

function fmtToolInput(input: unknown): string {
  if (input === undefined || input === null) return '';
  try {
    return typeof input === 'string' ? input : JSON.stringify(input);
  } catch {
    return String(input);
  }
}

function fmtToolOutput(out: unknown): string {
  if (out === undefined || out === null) return '';
  const s = typeof out === 'string' ? out : JSON.stringify(out, null, 2);
  if (!s || s === 'null' || s === '""') return '';
  return s.length > 800 ? s.slice(0, 800) + ' …' : s;
}
