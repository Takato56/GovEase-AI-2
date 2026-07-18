import { marked } from 'marked';

marked.use({
  gfm: true,
  breaks: true,
});

const stripUnsafeHtml = (html) =>
  html
    .replace(/<script[\s\S]*?>[\s\S]*?<\/script>/gi, '')
    .replace(/\son\w+="[^"]*"/gi, '')
    .replace(/\son\w+='[^']*'/gi, '')
    .replace(/javascript:/gi, '');

export const renderMarkdown = (content) => stripUnsafeHtml(marked.parse(content || ''));

export const stripMarkdown = (content) =>
  (content || '')
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/[#>*_\-[\]()]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();

export const messagesToMarkdown = (messages) => {
  const lines = [
    '# GovEase AI Chat Transcript',
    '',
    `Thời gian xuất: ${new Date().toLocaleString('vi-VN')}`,
    '',
  ];

  messages.forEach((message) => {
    const title = message.role === 'user' ? 'Người dân' : 'Trợ lý AI';
    lines.push(`## ${title}`, '', message.content.trim(), '');
  });

  return lines.join('\n');
};
