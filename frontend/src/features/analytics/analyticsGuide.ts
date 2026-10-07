// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// analyticsGuide - "How it works" content for the Analytics module.
// Consumed by <ModuleGuideButton content={analyticsGuide} /> on AnalyticsPage.
//
// i18n: every key carries its inline English default and is read via
// t(key, { defaultValue }). The keys are not in en.ts, the inline defaults
// are the English source; their translations live in the other locale files,
// so a changed default needs its translations redone too.

import type { ModuleGuideContent } from '@/shared/ui';

export const analyticsGuide: ModuleGuideContent = {
  titleKey: 'guide.analytics.title',
  titleDefault: 'Analytics',
  introKey: 'guide.analytics.intro',
  introDefault:
    'Analytics rolls budget against actual cost across every project into one portfolio view. Use it to see at a glance which jobs are over budget and by how much, without opening each project one by one.',
  sections: [
    {
      icon: 'Workflow',
      titleKey: 'guide.analytics.overview.title',
      titleDefault: 'A portfolio-wide rollup',
      bodyKey: 'guide.analytics.overview.body',
      bodyDefault:
        'This page aggregates the budget and actual cost of all your projects into one place. The figures come straight from your projects and their cost data, so there is nothing to enter here. Create a project or import a cost database and it appears automatically.',
    },
    {
      icon: 'Layers',
      titleKey: 'guide.analytics.kpis.title',
      titleDefault: 'The headline KPI cards',
      bodyKey: 'guide.analytics.kpis.body',
      bodyDefault:
        'Four cards summarise the whole portfolio: total projects, total budget against actual spend, the overall variance, and how many projects are at risk because they are over budget. A positive variance is shown in green and an overrun in red.',
    },
    {
      icon: 'Database',
      titleKey: 'guide.analytics.currency.title',
      titleDefault: 'Currencies stay separate',
      bodyKey: 'guide.analytics.currency.body',
      bodyDefault:
        'A EUR job is never blended with a USD one. When your projects span several currencies the totals break down per currency, each with its own figure and variance, so the headline numbers always make sense.',
    },
    {
      icon: 'ListChecks',
      titleKey: 'guide.analytics.compare.title',
      titleDefault: 'Compare projects in the table',
      bodyKey: 'guide.analytics.compare.body',
      bodyDefault:
        'The comparison table lists every project with its budget, actual, variance, variance percent and an on-budget or over-budget status. Click any column header to sort, click a row to open that project, or use the wallet button to jump straight to its Finance module.',
    },
    {
      icon: 'Search',
      titleKey: 'guide.analytics.filter.title',
      titleDefault: 'Search, filter and chart',
      bodyKey: 'guide.analytics.filter.body',
      bodyDefault:
        'Narrow the table by searching for a project name or filtering by region and status. The budget breakdown chart below mirrors the rows in view, plotting planned against actual cost as bars so overruns are easy to spot.',
    },
    {
      icon: 'Rocket',
      titleKey: 'guide.analytics.export.title',
      titleDefault: 'Export the comparison',
      bodyKey: 'guide.analytics.export.body',
      bodyDefault:
        'Use Export CSV to download the full filtered comparison for a spreadsheet or a report. For the role-by-role KPI view switch to Reporting, and open Finance on any project to trace a figure back to its source.',
    },
  ],
  ctaKey: 'guide.analytics.cta',
  ctaDefault: 'Review your projects',
};
