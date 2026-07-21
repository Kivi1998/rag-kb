-- V013: chat_session 新增标题字段,供历史会话列表展示
-- 首条用户消息写入时截取前 30 字符作为标题,只在标题为空时写入一次;可空,新建会话尚无消息时为空

ALTER TABLE chat_session ADD COLUMN title VARCHAR(64);
