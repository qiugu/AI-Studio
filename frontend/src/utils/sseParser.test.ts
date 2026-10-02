import { describe, expect, it } from 'vitest'

import { SSEParser } from './sseParser'

describe('SSEParser', () => {
  it('parses CRLF frames split across chunks', () => {
    const parser = new SSEParser()

    expect(parser.feed('event: message\r\ndata: {"content":"中"}\r')).toEqual([])
    expect(parser.feed('\n\r\n')).toEqual([
      { event: 'message', data: '{"content":"中"}' },
    ])
  })

  it('supports LF and CR framing and ignores heartbeat comments', () => {
    const parser = new SSEParser()

    expect(parser.feed(': ping\n\nevent: done\ndata: {}\n\n')).toEqual([
      { event: 'done', data: '{}' },
    ])
    expect(parser.feed('event: error\rdata: {"error":"x"}\r\r')).toEqual([
      { event: 'error', data: '{"error":"x"}' },
    ])
  })

  it('joins multiple data fields with LF', () => {
    const parser = new SSEParser()

    expect(parser.feed('event: message\ndata: first\ndata: second\n\n')).toEqual([
      { event: 'message', data: 'first\nsecond' },
    ])
  })
})
