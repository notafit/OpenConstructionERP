// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Component tests for <WorkPackageSovPicker>.
//
// The picker sets the default SOV line a work package's billing rolls up to.
// Pinned here: only billable lines are offered (a grouping line is never
// billed directly, so picking one would make every amount "unmapped"); an
// agreement that names its prime contract is offered that contract's lines
// only; and "not linked" clears the link rather than sending an empty string.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('@/features/contracts/api', () => ({
  listContracts: vi.fn(),
  listContractLines: vi.fn(),
}));

vi.mock('./api', () => ({
  updateWorkPackage: vi.fn(),
}));

vi.mock('@/stores/useToastStore', () => ({
  useToastStore: (sel: (s: { addToast: () => void }) => unknown) => sel({ addToast: vi.fn() }),
}));

import { WorkPackageSovPicker, billableLines } from './WorkPackageSovPicker';
import * as contractsApi from '@/features/contracts/api';
import * as subsApi from './api';
import type { ContractItem, ContractLine } from '@/features/contracts/api';
import type { Agreement, WorkPackage } from './api';

const contractsMock = vi.mocked(contractsApi.listContracts);
const linesMock = vi.mocked(contractsApi.listContractLines);
const updateMock = vi.mocked(subsApi.updateWorkPackage);

function contract(id: string, code: string): ContractItem {
  return { id, code, title: `Prime ${code}`, project_id: 'p-1' } as ContractItem;
}

function line(id: string, code: string, parent: string | null = null, contractId = 'ct-1'): ContractLine {
  return { id, code, description: `Line ${code}`, parent_line_id: parent, contract_id: contractId } as ContractLine;
}

const agreement = { id: 'ag-1', project_id: 'p-1', prime_contract_id: null } as Agreement;
const workPackage = { id: 'wp-1', agreement_id: 'ag-1', name: 'Footings', contract_line_id: null } as WorkPackage;

function renderPicker(ag: Agreement = agreement, wp: WorkPackage = workPackage) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <WorkPackageSovPicker agreement={ag} workPackage={wp} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('billableLines', () => {
  it('drops every line another line hangs under', () => {
    const lines = [line('g', '03'), line('a', '03.10', 'g'), line('b', '04')];
    expect(billableLines(lines).map((ln) => ln.id)).toEqual(['a', 'b']);
  });
});

describe('WorkPackageSovPicker', () => {
  it('offers only the named prime contract, and only its billable lines', async () => {
    contractsMock.mockResolvedValue({
      items: [contract('ct-1', 'PC-1'), contract('ct-2', 'PC-2')],
      total: 2,
      offset: 0,
      limit: 50,
    });
    linesMock.mockImplementation(async (id: string) =>
      id === 'ct-2'
        ? [line('g', '03', null, 'ct-2'), line('a', '03.10', 'g', 'ct-2')]
        : [line('x', '99', null, 'ct-1')],
    );
    renderPicker({ ...agreement, prime_contract_id: 'ct-2' });

    const select = await screen.findByTestId('wp-sov-picker');
    await waitFor(() => expect(within(select).getAllByRole('option')).toHaveLength(2));
    const values = within(select)
      .getAllByRole('option')
      .map((o) => (o as HTMLOptionElement).value);
    expect(values).toEqual(['', 'a']);
    expect(linesMock).toHaveBeenCalledWith('ct-2');
    expect(linesMock).not.toHaveBeenCalledWith('ct-1');
  });

  it('links a line, and "not linked" clears the link to null', async () => {
    contractsMock.mockResolvedValue({ items: [contract('ct-1', 'PC-1')], total: 1, offset: 0, limit: 50 });
    linesMock.mockResolvedValue([line('a', '03.10')]);
    updateMock.mockResolvedValue({} as WorkPackage);
    renderPicker(agreement, { ...workPackage, contract_line_id: 'a' });

    const select = await screen.findByTestId('wp-sov-picker');
    await waitFor(() => expect(within(select).getAllByRole('option')).toHaveLength(2));
    fireEvent.change(select, { target: { value: '' } });
    await waitFor(() => expect(updateMock).toHaveBeenCalledWith('wp-1', { contract_line_id: null }));

    fireEvent.change(select, { target: { value: 'a' } });
    await waitFor(() => expect(updateMock).toHaveBeenCalledWith('wp-1', { contract_line_id: 'a' }));
  });

  it('says so when the project has no client contract to bill against', async () => {
    contractsMock.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 50 });
    renderPicker();
    expect(await screen.findByTestId('wp-sov-no-contract')).toBeInTheDocument();
  });
});
