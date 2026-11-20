// The caption bar shown while the Demo story plays: stage dots a-g, caption, Next / Stop / Reset.

import { STAGES, type Story } from "../useDemoStory";

export function StoryBar({ story, onNext, onStop, onReset, onDismiss }: {
  story: Story; onNext: () => void; onStop: () => void; onReset: () => void; onDismiss: () => void;
}) {
  if (story.error) {
    return (
      <div role="alert" className="flex items-center gap-3 border-b border-critical/40 bg-critical/10 px-5 py-2.5 text-sm">
        <span className="font-medium text-up">Demo story stopped:</span>
        <span className="text-ink-2">{story.error}</span>
        <button onClick={onDismiss} className="ml-auto rounded-md border border-line px-2.5 py-1 text-xs hover:bg-raised">Close</button>
      </div>
    );
  }
  if (story.stage < 0) return null;
  const done = story.stage >= STAGES.length;

  return (
    <div className="border-b border-ai/40 bg-ai/10 px-5 py-3" aria-live="polite">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <span className="text-[11px] font-bold uppercase tracking-wider text-ai">Demo story</span>
        <ol className="flex items-center gap-1" aria-label="Story progress">
          {STAGES.map((s, i) => (
            <li key={s.key} title={s.title}
                className={`flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px]
                  ${i === story.stage ? "bg-ai text-white" : i < story.stage || done ? "bg-ai/25 text-ink-2" : "bg-raised text-muted"}`}>
              <span className="font-semibold">{s.key}</span>
              {i === story.stage && <span>{s.title}</span>}
            </li>
          ))}
        </ol>
        <div className="ml-auto flex gap-2">
          {story.running && (
            <>
              <button onClick={onNext} className="rounded-md bg-ai px-3 py-1 text-xs font-medium text-white hover:brightness-110">Next ▸</button>
              <button onClick={onStop} className="rounded-md border border-line px-3 py-1 text-xs hover:bg-raised">Stop</button>
            </>
          )}
          <button onClick={onReset} className="rounded-md border border-line px-3 py-1 text-xs hover:bg-raised"
                  title="Stop the story and clear everything">Reset</button>
          {done && <button onClick={onDismiss} className="rounded-md border border-line px-3 py-1 text-xs hover:bg-raised">Close</button>}
        </div>
      </div>
      <p className="mt-2 text-[15px] leading-snug text-ink">{story.text}</p>
    </div>
  );
}
