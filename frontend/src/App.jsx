import React, { useEffect, useMemo, useRef, useState } from 'react';
import { messagesToMarkdown, renderMarkdown, stripMarkdown } from './lib/markdown.js';

const sampleFiles = [
  {
    title: 'Khai sinh',
    file: '/chat-samples/khai-sinh.md',
    summary: 'Liên thông khai sinh, bảo hiểm y tế cho trẻ dưới 6 tuổi',
  },
  {
    title: 'Tạm trú',
    file: '/chat-samples/tam-tru.md',
    summary: 'Hồ sơ, thời hạn và nơi tiếp nhận đăng ký tạm trú',
  },
  {
    title: 'Phản ánh',
    file: '/chat-samples/phan-anh.md',
    summary: 'Soạn phản ánh kiến nghị theo ngữ cảnh thủ tục',
  },
];

const quickQuestions = [
  'Hồ sơ đăng ký khai sinh gồm giấy tờ gì?',
  'Tạm trú trực tuyến cần điều kiện nào?',
  'Tôi muốn gửi phản ánh về hồ sơ chậm xử lý.',
];

const welcomeMessage = `## GovEase AI

Xin chào, tôi là trợ lý thử nghiệm cho dịch vụ công trực tuyến.

Bạn có thể gửi câu hỏi về khai sinh, tạm trú hoặc phản ánh kiến nghị.`;

const demoAnswer = (question) => {
  const normalized = question.toLowerCase();

  if (normalized.includes('tạm trú') || normalized.includes('tam tru')) {
    return `## Gợi ý tạm trú

Bạn có thể chuẩn bị trước:

1. Thông tin nơi ở hiện tại.
2. Giấy tờ chứng minh chỗ ở hợp pháp.
3. Thông tin cá nhân của người đăng ký.

> Đây là phản hồi mô phỏng khi backend chưa sẵn sàng.`;
  }

  if (normalized.includes('phản ánh') || normalized.includes('chậm')) {
    return `## Mẫu phản ánh

Bạn nên nêu rõ:

- Mã hồ sơ hoặc thủ tục liên quan.
- Cơ quan tiếp nhận.
- Thời điểm nộp hồ sơ.
- Nội dung cần được giải thích hoặc xử lý.

> Đây là phản hồi mô phỏng khi backend chưa sẵn sàng.`;
  }

  return `## Gợi ý khai sinh

Với thủ tục khai sinh, bạn thường cần kiểm tra:

- Giấy chứng sinh hoặc giấy tờ thay thế hợp lệ.
- Thông tin của cha, mẹ hoặc người đi đăng ký.
- Nơi cư trú và cơ quan tiếp nhận cấp xã.

> Đây là phản hồi mô phỏng khi backend chưa sẵn sàng.`;
};

const buildAssistantMarkdown = (data) => {
  const confidence =
    typeof data.confidence_score === 'number'
      ? `\n\n**Điểm tương đồng:** \`${data.confidence_score.toFixed(4)}\``
      : '';
  const source = data.source ? `\n\n**Nguồn:** ${data.source}` : '';

  return `## Trả lời

${data.answer || 'Chưa có nội dung trả lời.'}${source}${confidence}`;
};

function MarkdownView({ content }) {
  return (
    <div
      className="markdown-body"
      dangerouslySetInnerHTML={{ __html: renderMarkdown(content) }}
    />
  );
}

function App() {
  const [messages, setMessages] = useState([
    {
      id: 'assistant-welcome',
      role: 'assistant',
      content: welcomeMessage,
    },
  ]);
  const [draft, setDraft] = useState('## Câu hỏi\nTôi cần tư vấn thủ tục khai sinh cho trẻ dưới 6 tuổi.');
  const [apiState, setApiState] = useState('Sẵn sàng');
  const [isLoading, setIsLoading] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const fileInputRef = useRef(null);
  const transcriptRef = useRef(null);

  useEffect(() => {
    transcriptRef.current?.scrollTo({
      top: transcriptRef.current.scrollHeight,
      behavior: 'smooth',
    });
  }, [messages, isLoading]);

  const userMessageCount = useMemo(
    () => messages.filter((message) => message.role === 'user').length,
    [messages],
  );

  const handleSubmit = async (event) => {
    event?.preventDefault();
    const content = draft.trim();

    if (!content || isLoading) {
      return;
    }

    const userMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      content,
    };

    setMessages((current) => [...current, userMessage]);
    setDraft('');
    setIsLoading(true);
    setApiState('Đang gọi API');

    try {
      const response = await fetch('/bot/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: stripMarkdown(content) }),
      });

      if (!response.ok) {
        throw new Error(`API responded with ${response.status}`);
      }

      const data = await response.json();
      setMessages((current) => [
        ...current,
        {
          id: `assistant-${Date.now()}`,
          role: 'assistant',
          content: buildAssistantMarkdown(data),
        },
      ]);
      setApiState('Đã kết nối API');
    } catch (error) {
      setMessages((current) => [
        ...current,
        {
          id: `assistant-demo-${Date.now()}`,
          role: 'assistant',
          content: demoAnswer(content),
        },
      ]);
      setApiState('Demo offline');
    } finally {
      setIsLoading(false);
    }
  };

  const loadSample = async (file) => {
    const response = await fetch(file);
    const content = await response.text();
    setDraft(content);
  };

  const handleFileUpload = (event) => {
    const file = event.target.files?.[0];

    if (!file) {
      return;
    }

    const reader = new FileReader();
    reader.onload = () => {
      setDraft(String(reader.result || ''));
      event.target.value = '';
    };
    reader.readAsText(file, 'utf-8');
  };

  const exportTranscript = () => {
    const blob = new Blob([messagesToMarkdown(messages)], {
      type: 'text/markdown;charset=utf-8',
    });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = 'govease-chat-transcript.md';
    anchor.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="app">
      <header className="topbar">
        <div className="container topbar-inner">
          <a className="brand" href="/" aria-label="GovEase AI">
            <img src="/assets/govease-emblem.svg" alt="" className="brand-emblem" />
            <span>
              <strong>Cổng Dịch vụ công Quốc gia</strong>
              <small>GovEase AI thử nghiệm</small>
            </span>
          </a>

          <div className="account-actions">
            <button className="text-button" type="button">
              Đăng ký
            </button>
            <button className="primary-small" type="button">
              Đăng nhập
            </button>
          </div>

          <button
            className="icon-button mobile-menu-button"
            type="button"
            aria-label="Mở menu"
            onClick={() => setMobileMenuOpen((value) => !value)}
          >
            <span aria-hidden="true">=</span>
          </button>
        </div>
      </header>

      <nav className={`main-nav ${mobileMenuOpen ? 'is-open' : ''}`}>
        <div className="container nav-inner">
          <a className="home-link" href="/" aria-label="Trang chủ">
            <span aria-hidden="true">⌂</span>
          </a>
          <a className="active" href="#chat">
            Thông tin và dịch vụ
          </a>
          <a href="#payment">Thanh toán trực tuyến</a>
          <a href="#feedback">Phản ánh kiến nghị</a>
          <a href="#rating">Đánh giá chất lượng phục vụ</a>
          <a href="#support">Hỗ trợ</a>
        </div>
      </nav>

      <section className="search-band">
        <div className="container search-inner">
          <div className="search-copy">
            <span className="eyebrow">Trung tâm hỗ trợ thủ tục</span>
            <h1>Chatbot AI dịch vụ công</h1>
          </div>
          <form className="search-box" onSubmit={handleSubmit}>
            <input
              value={stripMarkdown(draft)}
              onChange={(event) => setDraft(`## Câu hỏi\n${event.target.value}`)}
              placeholder="Nhập từ khóa hoặc câu hỏi"
              aria-label="Nhập từ khóa hoặc câu hỏi"
            />
            <button type="submit">
              <span className="search-icon" aria-hidden="true" />
              Tra cứu
            </button>
          </form>
        </div>
      </section>

      <main className="container main-layout" id="chat">
        <aside className="tools-column" aria-label="Tệp kịch bản Markdown">
          <section className="tool-section">
            <h2>Tệp kịch bản .md</h2>
            <div className="sample-list">
              {sampleFiles.map((sample) => (
                <button
                  className="sample-item"
                  key={sample.file}
                  type="button"
                  onClick={() => loadSample(sample.file)}
                >
                  <span className="sample-title">{sample.title}</span>
                  <span className="sample-summary">{sample.summary}</span>
                </button>
              ))}
            </div>
          </section>

          <section className="tool-section facts">
            <h2>Phiên thử nghiệm</h2>
            <dl>
              <div>
                <dt>Trạng thái</dt>
                <dd>{apiState}</dd>
              </div>
              <div>
                <dt>Câu hỏi</dt>
                <dd>{userMessageCount}</dd>
              </div>
              <div>
                <dt>Định dạng</dt>
                <dd>Markdown</dd>
              </div>
            </dl>
          </section>
        </aside>

        <section className="chat-panel" aria-label="Khung chatbot AI">
          <div className="panel-header">
            <div>
              <span className="eyebrow">AI Assistant</span>
              <h2>Hỏi đáp thủ tục hành chính</h2>
            </div>
            <div className="panel-actions">
              <input
                ref={fileInputRef}
                className="visually-hidden"
                type="file"
                accept=".md,text/markdown,text/plain"
                onChange={handleFileUpload}
              />
              <button
                className="icon-label-button"
                type="button"
                onClick={() => fileInputRef.current?.click()}
              >
                <span aria-hidden="true">↑</span>
                Nạp .md
              </button>
              <button className="icon-label-button" type="button" onClick={exportTranscript}>
                <span aria-hidden="true">↓</span>
                Xuất .md
              </button>
              <button
                className="icon-button"
                type="button"
                aria-label="Xóa hội thoại"
                onClick={() =>
                  setMessages([
                    {
                      id: 'assistant-welcome-reset',
                      role: 'assistant',
                      content: welcomeMessage,
                    },
                  ])
                }
              >
                <span aria-hidden="true">×</span>
              </button>
            </div>
          </div>

          <div className="transcript" ref={transcriptRef}>
            {messages.map((message) => (
              <article className={`message ${message.role}`} key={message.id}>
                <div className="message-meta">
                  <span>{message.role === 'user' ? 'Người dân' : 'Trợ lý AI'}</span>
                  <time>{new Date().toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' })}</time>
                </div>
                <MarkdownView content={message.content} />
              </article>
            ))}
            {isLoading && (
              <article className="message assistant pending">
                <div className="typing" aria-label="Đang xử lý">
                  <span />
                  <span />
                  <span />
                </div>
              </article>
            )}
          </div>

          <div className="quick-row" aria-label="Câu hỏi nhanh">
            {quickQuestions.map((question) => (
              <button key={question} type="button" onClick={() => setDraft(`## Câu hỏi\n${question}`)}>
                {question}
              </button>
            ))}
          </div>

          <form className="composer" onSubmit={handleSubmit}>
            <textarea
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder="## Câu hỏi"
              rows={5}
              aria-label="Nội dung Markdown"
            />
            <button className="send-button" type="submit" disabled={isLoading || !draft.trim()}>
              <span aria-hidden="true">→</span>
              Gửi thử nghiệm
            </button>
          </form>
        </section>
      </main>

      <footer className="footer" id="support">
        <div className="container footer-inner">
          <span>Cơ quan chủ quản: Văn phòng Chính phủ</span>
          <span>www.dichvucong.gov.vn</span>
          <span>Tổng đài hỗ trợ: 18001096</span>
          <span>Email: dichvucong@chinhphu.vn</span>
        </div>
      </footer>
    </div>
  );
}

export default App;
