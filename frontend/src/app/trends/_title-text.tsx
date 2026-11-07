import React from 'react';
import styles from './page.module.css';

const segmenter = typeof Intl.Segmenter === 'function'
  ? new Intl.Segmenter('zh-CN', { granularity: 'word' })
  : null;

/** Keep Chinese words such as “最高” and “美元” together without altering a raw title. */
export default function TitleText({ title }: { title: string }) {
  if (!segmenter) return <>{title}</>;
  return <>{Array.from(segmenter.segment(title), (part, index) => (
    part.isWordLike && /\p{Script=Han}/u.test(part.segment)
      ? <span key={index} className={styles.titleWord}>{part.segment}</span>
      : <React.Fragment key={index}>{part.segment}</React.Fragment>
  ))}</>;
}
