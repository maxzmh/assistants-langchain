import { Button, List, Popconfirm, Typography, Empty } from '@douyinfe/semi-ui';
import { IconPlus, IconDelete } from '@douyinfe/semi-icons';
import type { SessionItem } from '../lib/api';

interface Props {
  sessions: SessionItem[];
  activeId: string | null;
  onNew: () => void;
  onSwitch: (id: string) => void;
  onDelete: (id: string) => void;
}

/** 左侧会话列表：新建、切换、删除。数据由父层拉取并下发。 */
export function Sidebar({ sessions, activeId, onNew, onSwitch, onDelete }: Props) {

  return (
    <aside className="sidebar">
      <div className="sidebar-top">
        <Button
          theme="solid"
          type="primary"
          icon={<IconPlus />}
          block
          onClick={onNew}
        >
          新对话
        </Button>
      </div>
      <div className="sidebar-list">
        <Typography.Text type="tertiary" size="small" style={{ padding: '6px 12px' }}>
          历史会话
        </Typography.Text>
        {sessions.length === 0 ? (
          <Empty
            image={null}
            description="还没有历史会话"
            style={{ padding: '20px 0' }}
          />
        ) : (
          <List
            dataSource={sessions}
            split={false}
            renderItem={(s) => {
              const active = s.session_id === activeId;
              return (
                <div
                  className={'session-item' + (active ? ' active' : '')}
                  onClick={() => onSwitch(s.session_id)}
                >
                  <span className="session-title">{s.title || '新对话'}</span>
                  <Popconfirm
                    title="删除会话"
                    content="确定删除这个会话吗？"
                    okType="danger"
                    onConfirm={(e) => {
                      e?.stopPropagation?.();
                      onDelete(s.session_id);
                    }}
                    onCancel={(e) => e?.stopPropagation?.()}
                  >
                    <Button
                      className="session-del"
                      type="tertiary"
                      theme="borderless"
                      size="small"
                      icon={<IconDelete />}
                      onClick={(e) => e.stopPropagation()}
                    />
                  </Popconfirm>
                </div>
              );
            }}
          />
        )}
      </div>
    </aside>
  );
}
