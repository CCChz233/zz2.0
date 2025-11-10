-- 商机洞察表（opportunity_insights）
-- 用于存储大模型分析后的商机判断结果

CREATE TABLE IF NOT EXISTS public.opportunity_insights (
  -- 主键：关联原始商机表
  opportunity_id uuid NOT NULL PRIMARY KEY REFERENCES public."00_opportunity"(id) ON DELETE CASCADE,
  
  -- 清洗后的文本
  clean_text text,
  
  -- 核心分析结果
  title text,
  short_summary text,              -- ≤120字摘要
  noteworthy boolean NOT NULL DEFAULT false,  -- 是否值得关注
  priority text NOT NULL DEFAULT 'low' CHECK (priority IN ('high', 'medium', 'low')),
  confidence numeric(3,2) DEFAULT 0.5 CHECK (confidence >= 0 AND confidence <= 1),
  
  -- 结构化数据（JSONB）
  reasons jsonb DEFAULT '[]'::jsonb,        -- 理由列表（2-5条）
  actions jsonb DEFAULT '[]'::jsonb,         -- 建议动作（1-3条）
  tags jsonb DEFAULT '[]'::jsonb,            -- 标签（2-5个）
  raw_json jsonb,                            -- 完整的模型原始输出
  
  -- 透传字段（来自原始表）
  source_url text,
  publish_time timestamp with time zone,
  source_type text,
  news_type text,
  
  -- 元数据
  model text,                                -- 使用的模型名称（如 qwen3-max）
  created_at timestamp with time zone DEFAULT now(),
  updated_at timestamp with time zone DEFAULT now()
) TABLESPACE pg_default;

-- 索引
CREATE INDEX IF NOT EXISTS idx_opportunity_insights_noteworthy ON public.opportunity_insights(noteworthy) WHERE noteworthy = true;
CREATE INDEX IF NOT EXISTS idx_opportunity_insights_priority ON public.opportunity_insights(priority);
CREATE INDEX IF NOT EXISTS idx_opportunity_insights_publish_time ON public.opportunity_insights(publish_time DESC);
CREATE INDEX IF NOT EXISTS idx_opportunity_insights_updated_at ON public.opportunity_insights(updated_at DESC);

-- 更新触发器（自动更新 updated_at）
CREATE OR REPLACE FUNCTION update_opportunity_insights_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_opportunity_insights_updated_at
  BEFORE UPDATE ON public.opportunity_insights
  FOR EACH ROW
  EXECUTE FUNCTION update_opportunity_insights_updated_at();

-- 注释
COMMENT ON TABLE public.opportunity_insights IS '商机AI分析洞察表：存储大模型对商机的判断结果（是否值得关注、优先级、建议动作等）';
COMMENT ON COLUMN public.opportunity_insights.noteworthy IS '是否值得关注（对公司有潜在价值/影响）';
COMMENT ON COLUMN public.opportunity_insights.priority IS '优先级：high/medium/low';
COMMENT ON COLUMN public.opportunity_insights.reasons IS '值得关注的理由列表（JSONB数组）';
COMMENT ON COLUMN public.opportunity_insights.actions IS '建议动作列表（JSONB数组）';
COMMENT ON COLUMN public.opportunity_insights.tags IS '标签列表（JSONB数组）';
COMMENT ON COLUMN public.opportunity_insights.raw_json IS '大模型原始输出的完整JSON';

