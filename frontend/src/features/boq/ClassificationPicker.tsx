// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState, useMemo, useCallback, useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronRight, ChevronDown, Search, X, Tag } from 'lucide-react';
import clsx from 'clsx';

/* ── DIN 276 classification tree (Kostengruppen) ──────────────────────── */

interface ClassificationNode {
  code: string;
  label: string;
  children?: ClassificationNode[];
}

const DIN_276_TREE: ClassificationNode[] = [
  {
    code: '100',
    label: 'Grundstück / Land',
    children: [
      { code: '110', label: 'Grundstückswert / Land value' },
      { code: '120', label: 'Grundstücksnebenkosten / Incidental costs' },
      { code: '130', label: 'Freimachen / Clearing' },
    ],
  },
  {
    code: '200',
    label: 'Vorbereitende Maßnahmen / Preliminary works',
    children: [
      { code: '210', label: 'Herrichten / Site preparation' },
      { code: '220', label: 'Öffentliche Erschließung / Public development' },
      { code: '230', label: 'Nichtöffentliche Erschließung / Private development' },
      { code: '240', label: 'Ausgleichsmaßnahmen / Compensatory measures' },
      { code: '250', label: 'Übergangsmaßnahmen / Interim measures' },
    ],
  },
  {
    code: '300',
    label: 'Bauwerk – Baukonstruktionen / Building construction',
    children: [
      {
        code: '310',
        label: 'Baugrube / Excavation',
        children: [
          { code: '311', label: 'Baugrubenherstellung / Excavation work' },
          { code: '312', label: 'Baugrubenumschließung / Shoring' },
          { code: '313', label: 'Wasserhaltung / Dewatering' },
        ],
      },
      {
        code: '320',
        label: 'Gründung / Foundations',
        children: [
          { code: '321', label: 'Baugrundverbesserung / Ground improvement' },
          { code: '322', label: 'Flachgründungen / Shallow foundations' },
          { code: '323', label: 'Tiefgründungen / Deep foundations' },
          { code: '324', label: 'Unterböden u. Bodenplatten / Subfloors' },
          { code: '325', label: 'Bodenbeläge / Floor finishes' },
          { code: '326', label: 'Bauwerksabdichtung / Waterproofing' },
          { code: '327', label: 'Dränagen / Drainage' },
        ],
      },
      {
        code: '330',
        label: 'Außenwände / External walls',
        children: [
          { code: '331', label: 'Tragende Außenwände / Load-bearing ext. walls' },
          { code: '332', label: 'Nichttragende Außenwände / Non-load-bearing' },
          { code: '333', label: 'Außenstützen / External columns' },
          { code: '334', label: 'Außentüren u. -fenster / Ext. doors & windows' },
          { code: '335', label: 'Außenwandbekleidungen, außen / Ext. cladding' },
          { code: '336', label: 'Außenwandbekleidungen, innen / Int. lining' },
          { code: '337', label: 'Elementierte Außenwände / Prefab ext. walls' },
          { code: '338', label: 'Sonnenschutz / Sun protection' },
          { code: '339', label: 'Außenwände, sonstiges / Other' },
        ],
      },
      {
        code: '340',
        label: 'Innenwände / Internal walls',
        children: [
          { code: '341', label: 'Tragende Innenwände / Load-bearing int. walls' },
          { code: '342', label: 'Nichttragende Innenwände / Partitions' },
          { code: '343', label: 'Innenstützen / Internal columns' },
          { code: '344', label: 'Innentüren u. -fenster / Int. doors & windows' },
          { code: '345', label: 'Innenwandbekleidungen / Int. wall finishes' },
          { code: '346', label: 'Elementierte Innenwände / Prefab int. walls' },
        ],
      },
      {
        code: '350',
        label: 'Decken / Floors/slabs',
        children: [
          { code: '351', label: 'Deckenkonstruktionen / Floor structures' },
          { code: '352', label: 'Deckenbeläge / Floor finishes' },
          { code: '353', label: 'Deckenbekleidungen / Ceiling finishes' },
        ],
      },
      {
        code: '360',
        label: 'Dächer / Roofs',
        children: [
          { code: '361', label: 'Dachkonstruktionen / Roof structures' },
          { code: '362', label: 'Dachfenster, Dachöffnungen / Roof windows' },
          { code: '363', label: 'Dachbeläge / Roof coverings' },
          { code: '364', label: 'Dachbekleidungen / Roof lining' },
        ],
      },
      {
        code: '370',
        label: 'Baukonstruktive Einbauten / Structural fittings',
        children: [
          { code: '371', label: 'Allgemeine Einbauten / General fittings' },
          { code: '372', label: 'Besondere Einbauten / Special fittings' },
        ],
      },
      {
        code: '390',
        label: 'Sonstige Baukonstruktionen / Other construction',
      },
    ],
  },
  {
    code: '400',
    label: 'Bauwerk – Technische Anlagen / Building services',
    children: [
      { code: '410', label: 'Abwasser-, Wasser-, Gasanlagen / Plumbing' },
      { code: '420', label: 'Wärmeversorgungsanlagen / Heating' },
      { code: '430', label: 'Raumlufttechnische Anlagen / HVAC' },
      { code: '440', label: 'Starkstromanlagen / Electrical power' },
      { code: '450', label: 'Fernmelde- u. IT-Anlagen / Telecom & IT' },
      { code: '460', label: 'Förderanlagen / Conveying systems' },
      { code: '470', label: 'Nutzungsspezifische Anlagen / Use-specific' },
      { code: '480', label: 'Gebäudeautomation / Building automation' },
      { code: '490', label: 'Sonstige techn. Anlagen / Other services' },
    ],
  },
  {
    code: '500',
    label: 'Außenanlagen / External works',
    children: [
      { code: '510', label: 'Geländeflächen / Terrain' },
      { code: '520', label: 'Befestigte Flächen / Paved areas' },
      { code: '530', label: 'Baukonstruktionen Außenanlagen / Ext. structures' },
      { code: '540', label: 'Technische Anlagen Außenanlagen / Ext. services' },
      { code: '550', label: 'Einbauten Außenanlagen / Ext. fittings' },
      { code: '590', label: 'Sonstige Außenanlagen / Other external' },
    ],
  },
  {
    code: '600',
    label: 'Ausstattung und Kunstwerke / Furnishing & artwork',
    children: [
      { code: '610', label: 'Ausstattung / Furnishing' },
      { code: '620', label: 'Kunstwerke / Artwork' },
    ],
  },
  {
    code: '700',
    label: 'Baunebenkosten / Construction overhead',
    children: [
      { code: '710', label: 'Bauherrenaufgaben / Client tasks' },
      { code: '720', label: 'Vorbereitung Objektplanung / Design preparation' },
      { code: '730', label: 'Architekten- u. Ingenieurleistungen / A&E fees' },
      { code: '740', label: 'Gutachten u. Beratung / Consulting' },
      { code: '750', label: 'Kunst / Art' },
      { code: '760', label: 'Finanzierung / Financing' },
      { code: '770', label: 'Allgemeine Baunebenkosten / General overhead' },
      { code: '790', label: 'Sonstige Baunebenkosten / Other overhead' },
    ],
  },
  {
    code: '800',
    label: 'Finanzierung / Financing',
  },
];

/* ── NRM classification tree (simplified top levels) ──────────────────── */

const NRM_TREE: ClassificationNode[] = [
  { code: '0', label: 'Facilitating works' },
  { code: '1', label: 'Substructure' },
  {
    code: '2',
    label: 'Superstructure',
    children: [
      { code: '2.1', label: 'Frame' },
      { code: '2.2', label: 'Upper floors' },
      { code: '2.3', label: 'Roof' },
      { code: '2.4', label: 'Stairs and ramps' },
      { code: '2.5', label: 'External walls' },
      { code: '2.6', label: 'Windows and external doors' },
      { code: '2.7', label: 'Internal walls and partitions' },
      { code: '2.8', label: 'Internal doors' },
    ],
  },
  {
    code: '3',
    label: 'Internal finishes',
    children: [
      { code: '3.1', label: 'Wall finishes' },
      { code: '3.2', label: 'Floor finishes' },
      { code: '3.3', label: 'Ceiling finishes' },
    ],
  },
  { code: '4', label: 'Fittings, furnishings and equipment' },
  {
    code: '5',
    label: 'Services',
    children: [
      { code: '5.1', label: 'Sanitary installations' },
      { code: '5.2', label: 'Services equipment' },
      { code: '5.3', label: 'Disposal installations' },
      { code: '5.4', label: 'Water installations' },
      { code: '5.5', label: 'Heat source' },
      { code: '5.6', label: 'Space heating and air conditioning' },
      { code: '5.7', label: 'Ventilation' },
      { code: '5.8', label: 'Electrical installations' },
      { code: '5.9', label: 'Fuel installations' },
      { code: '5.10', label: 'Lift and conveyor installations' },
      { code: '5.11', label: 'Fire and lightning protection' },
      { code: '5.12', label: 'Communication/security/control' },
      { code: '5.13', label: 'Special installations' },
      { code: '5.14', label: "Builder's work in connection with services" },
    ],
  },
  { code: '6', label: 'Prefabricated buildings and building units' },
  { code: '7', label: 'Work to existing buildings' },
  { code: '8', label: 'External works' },
];

/* ── Division-based work-results tree (US/CA) ──────────────────────────
 * Division numbers are the interoperability keys and stay. The wording is
 * our own scope-of-work description, kept in step with the division scopes
 * in backend/app/modules/us_pack/config.py; the official titles are the
 * licensor's text and are not bundled. */

const MASTERFORMAT_TREE: ClassificationNode[] = [
  { code: '01', label: 'General project requirements and temporary provisions' },
  { code: '02', label: 'Demolition, site assessment and existing structures' },
  {
    code: '03', label: 'Cast-in-place and precast concrete work',
    children: [
      { code: '03 10 00', label: 'Formwork, shoring and embeds' },
      { code: '03 20 00', label: 'Rebar and mesh supply and placing' },
      { code: '03 30 00', label: 'Site-poured slabs, walls and frames' },
      { code: '03 40 00', label: 'Factory-cast panels and members' },
    ],
  },
  { code: '04', label: 'Brick, block and stone work' },
  {
    code: '05', label: 'Structural and miscellaneous metal work',
    children: [
      { code: '05 10 00', label: 'Steel frame: beams, columns, bracing' },
      { code: '05 20 00', label: 'Open-web steel joists' },
      { code: '05 30 00', label: 'Steel floor and roof deck' },
      { code: '05 50 00', label: 'Stairs, railings, lintels and misc. steel' },
    ],
  },
  {
    code: '06', label: 'Carpentry, millwork and composite framing',
    children: [
      { code: '06 10 00', label: 'Framing, blocking and sheathing' },
      { code: '06 20 00', label: 'Trim, shelving and interior joinery' },
      { code: '06 40 00', label: 'Custom cabinetry and panelling' },
    ],
  },
  { code: '07', label: 'Roofing, waterproofing and insulation' },
  {
    code: '08', label: 'Doors, windows and glazed assemblies',
    children: [
      { code: '08 10 00', label: 'Door leaves, frames and hardware sets' },
      { code: '08 40 00', label: 'Shopfronts, entrance systems and glass facades' },
      { code: '08 50 00', label: 'Window units' },
      { code: '08 80 00', label: 'Glass panes and glazing work' },
    ],
  },
  {
    code: '09', label: 'Interior finishing: drywall, flooring, painting',
    children: [
      { code: '09 20 00', label: 'Drywall partitions and plasterwork' },
      { code: '09 30 00', label: 'Ceramic and stone tile work' },
      { code: '09 50 00', label: 'Suspended and acoustic ceiling systems' },
      { code: '09 60 00', label: 'Floor coverings: resilient, carpet, timber' },
      { code: '09 90 00', label: 'Paint and protective coatings' },
    ],
  },
  { code: '10', label: 'Built-in specialty items and signage' },
  { code: '11', label: 'Fixed building equipment' },
  { code: '12', label: 'Furniture, casework and window treatments' },
  { code: '13', label: 'Pre-engineered and special-purpose structures' },
  { code: '14', label: 'Elevators, escalators and lifts' },
  { code: '21', label: 'Sprinkler and fire-suppression systems' },
  {
    code: '22', label: 'Piping systems and sanitary fixtures',
    children: [
      { code: '22 10 00', label: 'Water, waste and vent pipework, pumps' },
      { code: '22 30 00', label: 'Water heaters and softeners' },
      { code: '22 40 00', label: 'WCs, basins, sinks and showers' },
    ],
  },
  {
    code: '23', label: 'Heating, cooling and ventilation systems',
    children: [
      { code: '23 05 00', label: 'Mechanical supports, insulation, balancing' },
      { code: '23 20 00', label: 'Heating and chilled water pipework, pumps' },
      { code: '23 30 00', label: 'Ductwork, diffusers and fans' },
      { code: '23 60 00', label: 'Boilers and heat generation plant' },
      { code: '23 70 00', label: 'Air-handling units and packaged plant' },
    ],
  },
  {
    code: '26', label: 'Power distribution and lighting systems',
    children: [
      { code: '26 05 00', label: 'Conduit, cable, earthing and supports' },
      { code: '26 20 00', label: 'Switchboards, panels and final circuits' },
      { code: '26 40 00', label: 'Surge and corrosion protection' },
      { code: '26 50 00', label: 'Luminaires and lighting controls' },
    ],
  },
  { code: '27', label: 'Voice, data and network cabling' },
  { code: '28', label: 'Fire alarm, access control and surveillance' },
  { code: '31', label: 'Excavation, grading and earth support' },
  { code: '32', label: 'Paving, landscaping and site amenities' },
  { code: '33', label: 'Site water, sewer, storm and power services' },
];

/* ── SINAPI classification tree (Brazil) ──────────────────────────────── */

const SINAPI_TREE: ClassificationNode[] = [
  { code: '73', label: 'Servicos preliminares' },
  { code: '74', label: 'Movimento de terra' },
  { code: '75', label: 'Fundacoes e estruturas' },
  { code: '76', label: 'Paredes e paineis' },
  { code: '77', label: 'Coberturas e protecoes' },
  { code: '78', label: 'Forros' },
  { code: '79', label: 'Instalacoes eletricas' },
  { code: '80', label: 'Instalacoes hidro-sanitarias' },
  { code: '81', label: 'Revestimentos' },
  { code: '82', label: 'Pisos' },
  { code: '83', label: 'Esquadrias' },
  { code: '84', label: 'Vidros' },
  { code: '85', label: 'Pintura' },
  { code: '86', label: 'Servicos complementares' },
];

/* ── GB50500 classification tree (China) ─────────────────────────────── */

const GB50500_TREE: ClassificationNode[] = [
  { code: '01', label: 'Site preparation' },
  { code: '02', label: 'Foundation engineering' },
  { code: '03', label: 'Masonry engineering' },
  { code: '04', label: 'Concrete and RC engineering' },
  { code: '05', label: 'Structural steel engineering' },
  { code: '06', label: 'Metal structure engineering' },
  { code: '07', label: 'Wooden structure engineering' },
  { code: '08', label: 'Doors, windows and curtain walls' },
  { code: '09', label: 'Roofing engineering' },
  { code: '10', label: 'Waterproofing engineering' },
  { code: '11', label: 'Insulation engineering' },
  { code: '12', label: 'Decoration engineering' },
  { code: '13', label: 'Mechanical and electrical installation' },
];

/* ── Flatten for search ───────────────────────────────────────────────── */

function flattenTree(nodes: ClassificationNode[], parentPath = ''): Array<{ code: string; label: string; path: string }> {
  const result: Array<{ code: string; label: string; path: string }> = [];
  for (const node of nodes) {
    const path = parentPath ? `${parentPath} > ${node.code}` : node.code;
    result.push({ code: node.code, label: node.label, path });
    if (node.children) {
      result.push(...flattenTree(node.children, path));
    }
  }
  return result;
}

/* ── TreeNode component ───────────────────────────────────────────────── */

function TreeNode({
  node,
  depth,
  onSelect,
  selectedCode,
  expandedCodes,
  onToggle,
}: {
  node: ClassificationNode;
  depth: number;
  onSelect: (code: string, label: string) => void;
  selectedCode: string | null;
  expandedCodes: Set<string>;
  onToggle: (code: string) => void;
}) {
  const hasChildren = node.children && node.children.length > 0;
  const isExpanded = expandedCodes.has(node.code);
  const isSelected = selectedCode === node.code;

  return (
    <>
      <button
        onClick={() => {
          if (hasChildren) onToggle(node.code);
          onSelect(node.code, node.label);
        }}
        className={clsx(
          'flex w-full items-center gap-1.5 rounded-md px-2 py-1 text-left text-xs transition-colors',
          isSelected
            ? 'bg-oe-blue/10 text-oe-blue font-medium'
            : 'text-content-primary hover:bg-surface-secondary',
        )}
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
      >
        {hasChildren ? (
          <span className="shrink-0 w-4 h-4 flex items-center justify-center text-content-tertiary">
            {isExpanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          </span>
        ) : (
          <span className="shrink-0 w-4" />
        )}
        <span className="shrink-0 font-mono text-2xs text-content-tertiary w-8">{node.code}</span>
        <span className="truncate">{node.label}</span>
      </button>
      {hasChildren && isExpanded && node.children!.map((child) => (
        <TreeNode
          key={child.code}
          node={child}
          depth={depth + 1}
          onSelect={onSelect}
          selectedCode={selectedCode}
          expandedCodes={expandedCodes}
          onToggle={onToggle}
        />
      ))}
    </>
  );
}

/* ── Main ClassificationPicker component ──────────────────────────────── */

export type ClassificationStandard = 'din276' | 'nrm' | 'masterformat' | 'sinapi' | 'gb50500';

interface ClassificationPickerProps {
  /** Which standard to browse */
  standard?: ClassificationStandard;
  /** Currently selected code */
  value?: string | null;
  /** Called when user picks a code */
  onSelect: (code: string, label: string) => void;
  /** Optional: render as dropdown vs inline */
  mode?: 'dropdown' | 'inline';
  className?: string;
}

export function ClassificationPicker({
  standard = 'din276',
  value = null,
  onSelect,
  mode = 'dropdown',
  className,
}: ClassificationPickerProps) {
  const { t } = useTranslation();
  const [isOpen, setIsOpen] = useState(mode === 'inline');
  const [search, setSearch] = useState('');
  const [expandedCodes, setExpandedCodes] = useState<Set<string>>(new Set());
  const dropdownRef = useRef<HTMLDivElement>(null);

  const TREE_MAP: Record<ClassificationStandard, ClassificationNode[]> = {
    din276: DIN_276_TREE,
    nrm: NRM_TREE,
    masterformat: MASTERFORMAT_TREE,
    sinapi: SINAPI_TREE,
    gb50500: GB50500_TREE,
  };
  const tree = TREE_MAP[standard] ?? DIN_276_TREE;
  const flatItems = useMemo(() => flattenTree(tree), [tree]);

  // Filter by search
  const filteredItems = useMemo(() => {
    if (!search.trim()) return null; // Show tree view
    const q = search.toLowerCase();
    return flatItems.filter(
      (item) => item.code.toLowerCase().includes(q) || item.label.toLowerCase().includes(q),
    );
  }, [search, flatItems]);

  // Close on outside click
  useEffect(() => {
    if (mode !== 'dropdown' || !isOpen) return;
    function handleClickOutside(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [isOpen, mode]);

  const handleToggle = useCallback((code: string) => {
    setExpandedCodes((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  }, []);

  const handleSelect = useCallback(
    (code: string, label: string) => {
      onSelect(code, label);
      if (mode === 'dropdown') setIsOpen(false);
    },
    [onSelect, mode],
  );

  const selectedLabel = value ? flatItems.find((i) => i.code === value)?.label : null;

  // Dropdown trigger button
  const trigger = mode === 'dropdown' && (
    <button
      onClick={() => setIsOpen((prev) => !prev)}
      className={clsx(
        'flex items-center gap-1.5 h-7 rounded-md border border-border px-2 text-xs transition-colors',
        'hover:bg-surface-secondary focus:outline-none focus:ring-2 focus:ring-oe-blue/30',
        value ? 'text-content-primary' : 'text-content-tertiary',
        className,
      )}
    >
      <Tag size={11} className="shrink-0 text-content-tertiary" />
      {value ? (
        <span className="truncate max-w-[180px]">
          <span className="font-mono">{value}</span>
          {selectedLabel && <span className="ml-1 text-content-tertiary">– {(selectedLabel.split('/')[0] ?? '').trim()}</span>}
        </span>
      ) : (
        <span>{t('boq.select_classification', { defaultValue: 'Classification...' })}</span>
      )}
    </button>
  );

  const panel = (
    <div
      className={clsx(
        'flex flex-col bg-surface-elevated border border-border-light shadow-lg rounded-lg overflow-hidden',
        mode === 'dropdown' ? 'absolute left-0 top-full mt-1 z-50 w-72 max-h-80' : 'w-full h-full',
      )}
    >
      {/* Header */}
      <div className="flex items-center gap-2 border-b border-border-light p-2">
        <div className="flex items-center gap-1.5 flex-1 rounded-md bg-surface-secondary px-2 py-1">
          <Search size={12} className="text-content-tertiary shrink-0" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t('common.search', { defaultValue: 'Search...' })}
            className="flex-1 bg-transparent border-none outline-none text-xs text-content-primary placeholder:text-content-tertiary"
            autoFocus={mode === 'dropdown'}
          />
          {search && (
            <button aria-label={t('common.clear_search', { defaultValue: 'Clear search' })} onClick={() => setSearch('')} className="text-content-tertiary hover:text-content-primary">
              <X size={11} />
            </button>
          )}
        </div>
        <span className="text-2xs font-medium text-content-tertiary uppercase">{standard.toUpperCase()}</span>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto p-1">
        {filteredItems ? (
          // Search results — flat list
          filteredItems.length > 0 ? (
            filteredItems.map((item) => (
              <button
                key={item.code}
                onClick={() => handleSelect(item.code, item.label)}
                className={clsx(
                  'flex w-full items-center gap-2 rounded-md px-2 py-1 text-left text-xs transition-colors',
                  value === item.code
                    ? 'bg-oe-blue/10 text-oe-blue font-medium'
                    : 'text-content-primary hover:bg-surface-secondary',
                )}
              >
                <span className="shrink-0 font-mono text-2xs text-content-tertiary w-8">{item.code}</span>
                <span className="truncate">{item.label}</span>
              </button>
            ))
          ) : (
            <div className="py-6 text-center text-xs text-content-tertiary">
              {t('common.no_results', { defaultValue: 'No results found' })}
            </div>
          )
        ) : (
          // Tree view
          tree.map((node) => (
            <TreeNode
              key={node.code}
              node={node}
              depth={0}
              onSelect={handleSelect}
              selectedCode={value}
              expandedCodes={expandedCodes}
              onToggle={handleToggle}
            />
          ))
        )}
      </div>
    </div>
  );

  if (mode === 'inline') return panel;

  return (
    <div ref={dropdownRef} className="relative">
      {trigger}
      {isOpen && panel}
    </div>
  );
}
