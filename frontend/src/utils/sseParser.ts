export interface SSEEvent {
  event: string
  data: string
}

// Keep CRLF atomic. A generic "two line endings" expression can backtrack and
// treat the CR and LF inside one CRLF as an empty line, dropping the event name.
const EVENT_BOUNDARY = /(?:\r\n(?:\r\n|\r|\n)|\r(?:\r\n|\r)|\n(?:\r\n|\r|\n))/
const LINE_ENDING = /\r\n|\r|\n/

/**
 * Incrementally parses SSE frames across arbitrary network chunks.
 * Supports every line ending allowed by the HTML standard and ignores
 * comment-only frames such as sse-starlette heartbeat pings.
 */
export class SSEParser {
  private buffer = ''

  feed(chunk: string): SSEEvent[] {
    this.buffer += chunk
    const events: SSEEvent[] = []

    let boundary = EVENT_BOUNDARY.exec(this.buffer)
    while (boundary) {
      const frame = this.buffer.slice(0, boundary.index)
      this.buffer = this.buffer.slice(boundary.index + boundary[0].length)

      const event = this.parseFrame(frame)
      if (event) events.push(event)

      boundary = EVENT_BOUNDARY.exec(this.buffer)
    }

    return events
  }

  /** Parse a final frame when the transport closes without a blank line. */
  flush(): SSEEvent[] {
    if (!this.buffer) return []

    const frame = this.buffer
    this.buffer = ''
    const event = this.parseFrame(frame)
    return event ? [event] : []
  }

  private parseFrame(frame: string): SSEEvent | null {
    let eventType = 'message'
    const dataLines: string[] = []

    for (const line of frame.split(LINE_ENDING)) {
      if (!line || line.startsWith(':')) continue

      const colonIndex = line.indexOf(':')
      const field = colonIndex === -1 ? line : line.slice(0, colonIndex)
      let value = colonIndex === -1 ? '' : line.slice(colonIndex + 1)
      if (value.startsWith(' ')) value = value.slice(1)

      if (field === 'event') {
        eventType = value || 'message'
      } else if (field === 'data') {
        dataLines.push(value)
      }
    }

    if (dataLines.length === 0) return null
    return { event: eventType, data: dataLines.join('\n') }
  }
}
