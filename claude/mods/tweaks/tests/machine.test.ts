import type { Engine } from 'claude-code/testing'
import { describe, expect, test } from 'claude-code/testing'

import { world } from './world.js'

const NOW = Date.parse('2026-09-19T12:00:00Z')

/**
 * The machine's own lines of the block a prompt carries: everything under the
 * time and the two usage lines.
 *
 * @param $ the test's engine
 * @returns the lines
 */
const notesOf = async ($: Engine): Promise<string[]> => {
  const { context } = await $.prompt.submit({
    text: 'hello',
    origin: { kind: 'composer' },
    wait: false,
  })

  return (context?.at(-1) ?? '')
    .split('\n')
    .filter(line => line.startsWith('System pressure:') || line.startsWith('Low disk:'))
}

/**
 * A `df -Pk` report of one filesystem.
 *
 * @param available 1024-byte blocks free
 * @param capacity the used share, as df writes it
 * @returns the report
 */
const df = (available: number, capacity: string): string =>
  [
    'Filesystem 1024-blocks Used Available Capacity Mounted on',
    `/dev/sda1 1000000000 100000000 ${available} ${capacity} /`,
    `/dev/sda1 1000000000 100000000 ${available} ${capacity} /home/a`,
  ].join('\n')

describe('machine signals', () => {
  test('a load of one and a half times the cores is quiet, and a hair over is not', async ($, on) => {
    const seen = world(on, NOW)
    seen.files['/proc/loadavg'] = '6.00 1.10 1.20 1/500 1234\n'

    expect(await notesOf($)).toEqual([])

    seen.files['/proc/loadavg'] = '6.01 1.10 1.20 1/500 1234\n'

    expect(await notesOf($)).toEqual(['System pressure: load 6.01 on 4 cores'])
  })

  test('a memory stall over a tenth of the last ten seconds is reported', async ($, on) => {
    const seen = world(on, NOW)
    seen.files['/proc/pressure/memory'] = 'some avg10=10.00 avg60=0.00 total=0\n'

    expect(await notesOf($)).toEqual([])

    seen.files['/proc/pressure/memory'] = 'some avg10=10.01 avg60=0.00 total=0\n'

    expect(await notesOf($)).toEqual([
      'System pressure: 10.01% memory stall in the last 10s',
    ])
  })

  test('memory under a tenth available is reported', async ($, on) => {
    const seen = world(on, NOW)
    seen.files['/proc/meminfo'] = 'MemTotal:       16000000 kB\nMemAvailable:    1600000 kB\n'

    expect(await notesOf($)).toEqual([])

    seen.files['/proc/meminfo'] = 'MemTotal:       16000000 kB\nMemAvailable:    1599999 kB\n'

    expect(await notesOf($)).toEqual(['System pressure: 9% memory available'])
  })

  test('every shortage at once reads as one line', async ($, on) => {
    const seen = world(on, NOW)
    seen.files['/proc/loadavg'] = '9.00 1.10 1.20 1/500 1234\n'
    seen.files['/proc/pressure/memory'] = 'some avg10=42.00 avg60=0.00 total=0\n'
    seen.files['/proc/meminfo'] = 'MemTotal:       16000000 kB\nMemAvailable:     100000 kB\n'

    expect(await notesOf($)).toEqual([
      'System pressure: load 9.00 on 4 cores, 42% memory stall in the last 10s, 0% memory available',
    ])
  })

  test('a filesystem holding both / and the home directory is named once', async ($, on) => {
    const seen = world(on, NOW)
    seen.df = df(9 * 1048576, '89%')

    expect(await notesOf($)).toEqual(['Low disk: / has 9.0 GiB free (89% used)'])
  })

  test('a filesystem over 95% full is named however much it has free', async ($, on) => {
    const seen = world(on, NOW)
    seen.df = df(100 * 1048576, '96%')

    expect(await notesOf($)).toEqual(['Low disk: / has 100.0 GiB free (96% used)'])
  })

  test('ten free gibibytes is roomy', async ($, on) => {
    const seen = world(on, NOW)
    seen.df = df(10 * 1048576, '90%')

    expect(await notesOf($)).toEqual([])
  })

  test('a home on a filesystem of its own is named beside the root', async ($, on) => {
    const seen = world(on, NOW)
    seen.df = [
      'Filesystem 1024-blocks Used Available Capacity Mounted on',
      `/dev/sda1 1000000000 100000000 ${9 * 1048576} 89% /`,
      `/dev/sdb1 1000000000 100000000 ${1 * 1048576} 99% /home/a`,
    ].join('\n')

    expect(await notesOf($)).toEqual([
      'Low disk: / has 9.0 GiB free (89% used), /home/a has 1.0 GiB free (99% used)',
    ])
  })

  test('the macOS counters are read from the kernel', async ($, on) => {
    const seen = world(on, NOW)
    seen.host = 'Darwin'
    seen.sysctl = '4\n{ 9.00 2.05 2.11 }\n2\n'

    expect(await notesOf($)).toEqual([
      'System pressure: load 9.00 on 4 cores, memory pressure warning',
    ])

    seen.sysctl = '4\n{ 1.00 2.05 2.11 }\n4\n'

    expect(await notesOf($)).toEqual(['System pressure: memory pressure critical'])
  })

  test('a counter that cannot be read costs its own note and no other', async ($, on) => {
    const seen = world(on, NOW)
    seen.files['/proc/loadavg'] = '9.00 1.10 1.20 1/500 1234\n'
    delete seen.files['/proc/meminfo']

    expect(await notesOf($)).toEqual(['System pressure: load 9.00 on 4 cores'])
  })

  test('a df that fails leaves the pressure line standing', async ($, on) => {
    const seen = world(on, NOW)
    seen.files['/proc/loadavg'] = '9.00 1.10 1.20 1/500 1234\n'
    seen.df = ''
    seen.dfFails = true

    expect(await notesOf($)).toEqual(['System pressure: load 9.00 on 4 cores'])
  })
})
