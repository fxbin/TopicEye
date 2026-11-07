'use client';

import { ArrowRight } from 'lucide-react';
import type { TrendKeywordItem } from '@/types/trends';
import TitleText from './_title-text';
import styles from './_keyword-index.module.css';

export default function KeywordIndex({
  words,
  selectedKeyword,
  onSelect,
}: {
  words: TrendKeywordItem[];
  selectedKeyword: string | null;
  onSelect: (keyword: string) => void;
}) {
  return (
    <ol className={styles.index} aria-label="按收录内容数排序的关键词">
      {words.map((word, index) => (
        <li key={word.keyword}>
          <button
            type="button"
            className={styles.word}
            aria-label={`查看关键词「${word.keyword}」的来源明细`}
            aria-haspopup="dialog"
            aria-expanded={selectedKeyword === word.keyword}
            onClick={() => onSelect(word.keyword)}
          >
            <span className={styles.rank} aria-hidden>{String(index + 1).padStart(2, '0')}</span>
            <span className={styles.name}><TitleText title={word.keyword} /></span>
            <span className={styles.count}>{word.count.toLocaleString('zh-CN')}<span className={styles.unit}>条</span></span>
            <ArrowRight className={styles.arrow} size={16} aria-hidden />
          </button>
        </li>
      ))}
    </ol>
  );
}
