-- 正式标准化测评协议 2026.2。
-- 由 scripts/seed_protocol.py 执行；执行前必须设置 @protocol_publisher_id。
-- 不使用 USE 语句，以便支持通过 DB_NAME 配置的数据库名称。

-- 同一时刻只发布一组 A/B 正式任务。旧任务和历史会话不会被删除。
UPDATE assessment_tasks
SET status = 'closed', protocol_order = 0
WHERE protocol_order IN (1, 2)
  AND id NOT IN (
      'task-pitching-2026-2',
      'task-jumps-2026-2'
  );

INSERT INTO assessment_tasks (
    id, title, subject, description, scenario, estimated_minutes,
    requires_voice, protocol_order, stimulus_data, status,
    publisher_id, published_at
) VALUES (
    'task-pitching-2026-2',
    '最优投球机判断',
    'mathematics',
    '根据四台投球机相对于目标点的多次偏离距离，设计数学评价程序并判断哪台投球机表现最优。',
    '红色叉号代表理想落点，蓝色菱形代表实际落点，旁边数字表示该次投球到目标点的距离。请比较四台投球机，设计并说明一种合理的数学程序来综合评价各投球机的表现，最终明确判断哪台投球机表现最优，并说明理由。请在整个作答过程中持续口头说出你脑海中实时产生的所有想法。',
    12,
    TRUE,
    1,
    JSON_OBJECT(
        'type', 'scatter',
        'stimulus_version', '2026.2',
        'image_path', '/assessment/pitching-machines-zh.png',
        'image_title', '四台投球机落点与距离分布图',
        'image_sha256', '8c4b42cdc8f55d3b6c36603204e716985aab55b1eab02608f1e578427350e159',
        'target_label', '理想落点',
        'machines', JSON_ARRAY(
            JSON_OBJECT('name', '朗科投球机', 'distances', JSON_ARRAY(4.24, 2.23, 3.16, 3, 1)),
            JSON_OBJECT('name', '大力士自动投球机', 'distances', JSON_ARRAY(4, 3.16, 4.24, 3)),
            JSON_OBJECT('name', '火球投球机', 'distances', JSON_ARRAY(2, 1, 1, 1.41, 1.41)),
            JSON_OBJECT('name', '史密斯精品投球机', 'distances', JSON_ARRAY(3.61, 2.83, 3.61, 2.24, 2.24))
        )
    ),
    'published',
    @protocol_publisher_id,
    CURRENT_TIMESTAMP
) ON DUPLICATE KEY UPDATE
    title = VALUES(title),
    description = VALUES(description),
    scenario = VALUES(scenario),
    estimated_minutes = VALUES(estimated_minutes),
    protocol_order = VALUES(protocol_order),
    stimulus_data = VALUES(stimulus_data),
    status = 'published';

INSERT INTO assessment_tasks (
    id, title, subject, description, scenario, estimated_minutes,
    requires_voice, protocol_order, stimulus_data, status,
    publisher_id, published_at
) VALUES (
    'task-jumps-2026-2',
    '跨项目最优运动员判断',
    'mathematics',
    '根据跳高和跳远最佳成绩的频数分布，设计公平的跨项目评价程序并判断哪位运动员表现最优。',
    'Bill参加跳高，Joe参加跳远。表2给出了2000年跳高和跳远最佳成绩及其出现次数。请根据表格设计并说明一种公平的数学程序来比较两位运动员，最终明确判断Bill和Joe中哪位运动员表现最优，并说明理由。请在整个作答过程中持续口头说出你脑海中实时产生的所有想法。',
    12,
    TRUE,
    2,
    JSON_OBJECT(
        'type', 'athletes',
        'stimulus_version', '2026.2',
        'image_path', '/assessment/jump-performance-table-zh.png',
        'image_title', '2000年跳高与跳远最佳成绩频数表',
        'image_sha256', '528b8726eee06ac964583b5c12d01c3d526c76dcdf06d4c44d6f97bb23cea08f',
        'high_jump_frequency', JSON_ARRAY(
            JSON_OBJECT('height', '6英尺6英寸', 'count', 1),
            JSON_OBJECT('height', '6英尺8英寸', 'count', 2),
            JSON_OBJECT('height', '6英尺10英寸', 'count', 3),
            JSON_OBJECT('height', '7英尺0英寸', 'count', 5),
            JSON_OBJECT('height', '7英尺2英寸', 'count', 6),
            JSON_OBJECT('height', '7英尺4英寸', 'count', 7),
            JSON_OBJECT('height', '7英尺6英寸', 'count', 4),
            JSON_OBJECT('height', '7英尺8英寸', 'count', 1),
            JSON_OBJECT('height', '8英尺0英寸', 'count', NULL)
        ),
        'long_jump_frequency', JSON_ARRAY(
            JSON_OBJECT('length', '21英尺6英寸', 'count', 1),
            JSON_OBJECT('length', '22英尺0英寸', 'count', 2),
            JSON_OBJECT('length', '22英尺6英寸', 'count', 2),
            JSON_OBJECT('length', '23英尺0英寸', 'count', 9),
            JSON_OBJECT('length', '23英尺5英寸', 'count', 9),
            JSON_OBJECT('length', '24英尺6英寸', 'count', 4),
            JSON_OBJECT('length', '25英尺0英寸', 'count', 1),
            JSON_OBJECT('length', '25英尺6英寸', 'count', 1),
            JSON_OBJECT('length', '26英尺6英寸', 'count', NULL)
        )
    ),
    'published',
    @protocol_publisher_id,
    CURRENT_TIMESTAMP
) ON DUPLICATE KEY UPDATE
    title = VALUES(title),
    description = VALUES(description),
    scenario = VALUES(scenario),
    estimated_minutes = VALUES(estimated_minutes),
    protocol_order = VALUES(protocol_order),
    stimulus_data = VALUES(stimulus_data),
    status = 'published';

INSERT INTO scale_dimension_groups (
    id, task_id, dimension, label, description
) VALUES
('dim-monitoring-2026-2', 'task-pitching-2026-2', 'monitoring', '监控', '跟踪理解、进展、不确定性与错误。'),
('dim-control-2026-2', 'task-pitching-2026-2', 'controlDebugging', '控制与调试', '在遇到困难时调整策略、修正步骤与分配资源。'),
('dim-evaluation-2026-2', 'task-pitching-2026-2', 'evaluation', '评估', '判断方法与答案的有效性，并回顾整个问题解决过程。')
ON DUPLICATE KEY UPDATE
    task_id = VALUES(task_id),
    label = VALUES(label),
    description = VALUES(description);

INSERT INTO scale_items (
    id, group_id, dimension, self_report_text, observation_text,
    keywords, scale_min, scale_max, scoring_rubric, source, reversed, display_order
) VALUES
('zepeda23-monitoring-01', 'dim-monitoring-2026-2', 'monitoring',
 '在活动过程中，我发现自己会经常停下来检查自己的理解。',
 '检查自己是否理解任务内容。',
 '["停下来","检查理解","确认理解"]', 1, 7, '1=强烈不同意；7=强烈同意', 'Zepeda-2023-task-based', FALSE, 1),
('zepeda23-monitoring-02', 'dim-monitoring-2026-2', 'monitoring',
 '在活动过程中，我会持续关注自己对材料理解了多少，而不只是关注答案是否正确。',
 '持续跟踪理解程度。',
 '["理解程度","正确答案","持续关注"]', 1, 7, '1=强烈不同意；7=强烈同意', 'Zepeda-2023-task-based', FALSE, 2),
('zepeda23-monitoring-03', 'dim-monitoring-2026-2', 'monitoring',
 '在活动过程中，我会检查自己的理解是否足以解决新的问题。',
 '判断当前理解能否支持迁移到新问题。',
 '["新的问题","是否足够","检查理解"]', 1, 7, '1=强烈不同意；7=强烈同意', 'Zepeda-2023-task-based', FALSE, 3),
('zepeda23-monitoring-04', 'dim-monitoring-2026-2', 'monitoring',
 '在活动过程中，我会努力判断哪些概念自己还没有很好理解。',
 '识别尚未理解的概念。',
 '["哪些概念","没有理解","判断"]', 1, 7, '1=强烈不同意；7=强烈同意', 'Zepeda-2023-task-based', FALSE, 4),
('zepeda23-monitoring-05', 'dim-monitoring-2026-2', 'monitoring',
 '在活动过程中，我感觉自己逐渐理解了这些问题所涉及的概念和解题步骤。',
 '觉察概念和步骤理解的增长。',
 '["逐渐理解","概念","解题步骤"]', 1, 7, '1=强烈不同意；7=强烈同意', 'Zepeda-2023-task-based', FALSE, 5),
('zepeda23-monitoring-06', 'dim-monitoring-2026-2', 'monitoring',
 '在活动过程中，我会确认自己理解了如何正确解决这些问题。',
 '确认对正确解法的理解。',
 '["正确解决","确认","理解"]', 1, 7, '1=强烈不同意；7=强烈同意', 'Zepeda-2023-task-based', FALSE, 6),
('zepeda23-monitoring-07', 'dim-monitoring-2026-2', 'monitoring',
 '在活动过程中，我会努力理解自己所使用的解题步骤为什么有效。',
 '理解所用步骤的原理。',
 '["为什么有效","解题步骤","理解"]', 1, 7, '1=强烈不同意；7=强烈同意', 'Zepeda-2023-task-based', FALSE, 7),
('zepeda23-monitoring-08', 'dim-monitoring-2026-2', 'monitoring',
 '在活动过程中，我会关注自己对所使用解题步骤的理解程度。',
 '关注对当前解题步骤的理解。',
 '["理解程度","解题步骤","关注"]', 1, 7, '1=强烈不同意；7=强烈同意', 'Zepeda-2023-task-based', FALSE, 8),
('zepeda23-control-01', 'dim-control-2026-2', 'controlDebugging',
 '在活动过程中，当我感到困惑时，我会重新评估自己的假设。',
 '困惑时重新评估假设。',
 '["困惑","重新评估","假设"]', 1, 7, '1=强烈不同意；7=强烈同意', 'Zepeda-2023-task-based', FALSE, 9),
('zepeda23-control-02', 'dim-control-2026-2', 'controlDebugging',
 '在活动过程中，遇到不清楚的新信息时，我会停下来并返回重新查看。',
 '返回查看不清楚的信息。',
 '["不清楚","返回查看","停下来"]', 1, 7, '1=强烈不同意；7=强烈同意', 'Zepeda-2023-task-based', FALSE, 10),
('zepeda23-control-03', 'dim-control-2026-2', 'controlDebugging',
 '在活动过程中，当我无法理解问题时，我会改变策略。',
 '无法理解时改变策略。',
 '["改变策略","无法理解","问题"]', 1, 7, '1=强烈不同意；7=强烈同意', 'Zepeda-2023-task-based', FALSE, 11),
('zepeda23-control-04', 'dim-control-2026-2', 'controlDebugging',
 '在活动过程中，我会跟踪自己的进展，并在必要时改变方法或策略。',
 '根据进展调整方法或策略。',
 '["跟踪进展","必要时","改变方法"]', 1, 7, '1=强烈不同意；7=强烈同意', 'Zepeda-2023-task-based', FALSE, 12),
('zepeda23-control-05', 'dim-control-2026-2', 'controlDebugging',
 '在活动过程中，当我意识到自己的解题方式不正确时，我会纠正错误。',
 '发现解题错误后进行纠正。',
 '["纠正错误","不正确","意识到"]', 1, 7, '1=强烈不同意；7=强烈同意', 'Zepeda-2023-task-based', FALSE, 13),
('zepeda23-control-06', 'dim-control-2026-2', 'controlDebugging',
 '在活动过程中，当我对某些内容感到困惑时，我会返回并尝试把它弄明白。',
 '困惑时返回并澄清理解。',
 '["返回","弄明白","困惑"]', 1, 7, '1=强烈不同意；7=强烈同意', 'Zepeda-2023-task-based', FALSE, 14),
('zepeda23-control-07', 'dim-control-2026-2', 'controlDebugging',
 '在活动过程中，为了确保自己理解了材料，我会改变原来的学习或处理方式。',
 '为确保理解而调整处理方式。',
 '["改变方式","确保理解","材料"]', 1, 7, '1=强烈不同意；7=强烈同意', 'Zepeda-2023-task-based', FALSE, 15),
('zepeda23-control-08', 'dim-control-2026-2', 'controlDebugging',
 '在活动过程中，我会向自己提出问题，以确保自己理解了材料。',
 '通过自我提问检查理解。',
 '["自我提问","确保理解","材料"]', 1, 7, '1=强烈不同意；7=强烈同意', 'Zepeda-2023-task-based', FALSE, 16),
('zepeda23-control-09', 'dim-control-2026-2', 'controlDebugging',
 '在活动过程中，我没有考虑自己对材料理解得怎么样，而只是想尽快把问题做完。',
 '只追求尽快完成而不监控理解。',
 '["尽快做完","没有考虑","理解"]', 1, 7, '反向计分：计分值=8-原始作答', 'Zepeda-2023-task-based', TRUE, 17),
('zepeda23-evaluation-01', 'dim-evaluation-2026-2', 'evaluation',
 '在活动过程中，我会分析自己所用策略是否有用。',
 '分析所用策略的有效性。',
 '["策略是否有用","分析","有效性"]', 1, 7, '1=强烈不同意；7=强烈同意', 'Zepeda-2023-task-based', FALSE, 18),
('zepeda23-evaluation-02', 'dim-evaluation-2026-2', 'evaluation',
 '在活动过程中，我会回顾自己学到了什么。',
 '回顾已学习的内容。',
 '["回顾","学到了什么","总结"]', 1, 7, '1=强烈不同意；7=强烈同意', 'Zepeda-2023-task-based', FALSE, 19),
('zepeda23-evaluation-03', 'dim-evaluation-2026-2', 'evaluation',
 '在活动过程中，我会从头到尾检查自己对每个问题的解答。',
 '完整检查每道问题的解答。',
 '["从头到尾","检查解答","每个问题"]', 1, 7, '1=强烈不同意；7=强烈同意', 'Zepeda-2023-task-based', FALSE, 20),
('zepeda23-evaluation-04', 'dim-evaluation-2026-2', 'evaluation',
 '在活动过程中，我会检查自己的计算是否正确。',
 '检查计算结果。',
 '["检查计算","是否正确","计算结果"]', 1, 7, '1=强烈不同意；7=强烈同意', 'Zepeda-2023-task-based', FALSE, 21),
('zepeda23-evaluation-05', 'dim-evaluation-2026-2', 'evaluation',
 '在活动过程中，我会再次检查自己的解答，以确保做得正确。',
 '再次检查解答。',
 '["再次检查","确保正确","解答"]', 1, 7, '1=强烈不同意；7=强烈同意', 'Zepeda-2023-task-based', FALSE, 22),
('zepeda23-evaluation-06', 'dim-evaluation-2026-2', 'evaluation',
 '在活动过程中，我会回顾材料，以确保自己理解了其中的信息。',
 '回顾材料并确认理解。',
 '["回顾材料","确保理解","信息"]', 1, 7, '1=强烈不同意；7=强烈同意', 'Zepeda-2023-task-based', FALSE, 23),
('zepeda23-evaluation-07', 'dim-evaluation-2026-2', 'evaluation',
 '在活动过程中，我会检查自己是否理解了如何正确解决每一个问题。',
 '确认理解每道问题的正确解法。',
 '["每一个问题","正确解决","检查理解"]', 1, 7, '1=强烈不同意；7=强烈同意', 'Zepeda-2023-task-based', FALSE, 24)
ON DUPLICATE KEY UPDATE
    group_id = VALUES(group_id),
    self_report_text = VALUES(self_report_text),
    observation_text = VALUES(observation_text),
    keywords = VALUES(keywords),
    scale_min = VALUES(scale_min),
    scale_max = VALUES(scale_max),
    scoring_rubric = VALUES(scoring_rubric),
    source = VALUES(source),
    reversed = VALUES(reversed),
    display_order = VALUES(display_order);
