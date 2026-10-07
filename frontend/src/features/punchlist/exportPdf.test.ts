// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
//
// The punch list PDF had a route and no button, so nothing in the app could
// ever reach it. What is pinned here is the one request the new button makes:
// the exact route with its trailing slash (the router has redirect_slashes off,
// so the other form 404s), the project it is scoped to, and that it goes
// through the authenticated download helper, which turns a refusal into a
// message instead of saving a JSON error under a .pdf name.

import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return { ...actual, downloadWithAuth: vi.fn().mockResolvedValue(undefined) };
});

import { downloadPunchListPdf } from './api';
import * as api from '@/shared/lib/api';

const downloadMock = vi.mocked(api.downloadWithAuth);

describe('downloadPunchListPdf', () => {
  beforeEach(() => {
    downloadMock.mockClear();
  });

  it('asks the export route for this project, behind the bearer token', async () => {
    await downloadPunchListPdf('4f1c2b9e-0000-4000-8000-000000000001');

    expect(downloadMock).toHaveBeenCalledTimes(1);
    const [url, filename] = downloadMock.mock.calls[0]!;
    expect(url).toBe(
      '/api/v1/punchlist/export/pdf/?project_id=4f1c2b9e-0000-4000-8000-000000000001',
    );
    expect(filename).toBe('punchlist_4f1c2b9e-0000-4000-8000-000000000001.pdf');
  });

  it('does not send a locale the route would ignore', async () => {
    await downloadPunchListPdf('p1');
    expect(downloadMock.mock.calls[0]![0]).not.toContain('locale=');
  });

  it('passes a refusal on to the caller, so the page can say it', async () => {
    downloadMock.mockRejectedValueOnce(new Error('Project not found'));
    await expect(downloadPunchListPdf('p1')).rejects.toThrow('Project not found');
  });
});
