// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Case: "Roll subcontractor pay applications into your pay application".
//
// Universal: a main contractor's monthly bill to the owner is, line by line,
// mostly what its subcontractors billed it that month. The contractor links
// each subcontract work package to a line of the owner's schedule of values,
// files each sub's paperwork, approves the subs' applications for the period,
// and rolls them into its own claim, holding back any sub whose paperwork for
// the period is not on file. The paperwork is national: a lien waiver through
// the period end in the US, clearance certificates and no waiver in Germany,
// whatever the country pack states elsewhere. The step wording follows the
// labels on the subcontractor drawer and the claim's Subcontractor billing
// panel. Content strings are key plus inline English default and live only
// here.

import type { Playbook } from "../types";

const playbook: Playbook = {
  id: "roll-subcontractor-pay-applications-into-your-pay-application",
  order: 348,
  category: "commercial",
  companyTypes: ["general-contractor", "subcontractor", "project-manager"],
  roles: ["project-manager", "contract-administrator", "commercial-manager"],
  icon: "Combine",
  titleKey: "cases.roll_subcontractor_pay_applications_into_your_pay_application.title",
  titleDefault: "Roll subcontractor pay applications into your pay application",
  descKey: "cases.roll_subcontractor_pay_applications_into_your_pay_application.desc",
  descDefault:
    "Link each subcontract work package to a line of the owner's schedule of values, approve the subs' applications for the month, and roll them into your own claim line by line, holding back any sub whose waiver or certificates for the period are not on file.",
  estMinutes: 15,
  steps: [
    {
      id: "link",
      icon: "Route",
      inputs: [
        { labelKey: "cases.roll_subcontractor_pay_applications_into_your_pay_application.step.link.in.packages", label: "Subcontract work packages" },
        { labelKey: "cases.roll_subcontractor_pay_applications_into_your_pay_application.step.link.in.sov", label: "Owner schedule of values" },
      ],
      outputs: [
        { labelKey: "cases.roll_subcontractor_pay_applications_into_your_pay_application.step.link.out.linked", label: "Work package linked to an SOV line" },
        { labelKey: "cases.roll_subcontractor_pay_applications_into_your_pay_application.step.link.out.prime", label: "Prime contract named" },
      ],
      titleKey: "cases.roll_subcontractor_pay_applications_into_your_pay_application.step.link.title",
      titleDefault: "Link each work package to a line of the owner's schedule of values",
      whatKey: "cases.roll_subcontractor_pay_applications_into_your_pay_application.step.link.what",
      whatDefault:
        "Open the subcontractor and go to the Scope tab. Each agreement lists its work packages, and beside each one you choose the line of the client contract's schedule of values its billing belongs to. Only lines that are billed directly are offered, never a grouping line. If the project has more than one client contract, name the prime contract on the agreement first.",
      whyKey: "cases.roll_subcontractor_pay_applications_into_your_pay_application.step.link.why",
      whyDefault:
        "The link is what lets a sub's month land on the right line of your bill without anyone retyping it. It is set once per work package, and a single line of a sub's application can still be sent to another line later, on the claim itself.",
      moduleLabel: "Subcontractor Directory",
      moduleLabelKey: "nav.subcontractors",
      to: "/projects/:projectId/subcontractors",
    },
    {
      id: "require",
      icon: "ShieldCheck",
      inputs: [
        { labelKey: "cases.roll_subcontractor_pay_applications_into_your_pay_application.step.require.in.terms", label: "Subcontract payment terms" },
        { labelKey: "cases.roll_subcontractor_pay_applications_into_your_pay_application.step.require.in.certificates", label: "Sub's certificates" },
      ],
      outputs: [
        { labelKey: "cases.roll_subcontractor_pay_applications_into_your_pay_application.step.require.out.waiver", label: "Waiver requirement on the agreement" },
        { labelKey: "cases.roll_subcontractor_pay_applications_into_your_pay_application.step.require.out.checked", label: "Certificates on file" },
      ],
      titleKey: "cases.roll_subcontractor_pay_applications_into_your_pay_application.step.require.title",
      titleDefault: "Decide what each sub must hand over before payment",
      whatKey: "cases.roll_subcontractor_pay_applications_into_your_pay_application.step.require.what",
      whatDefault:
        "On the same agreement, switch on Require signed lien waiver before payment when the subcontract or the law asks for one, and check that the sub's certificates are on file. Both are judged at the end of your billing period. The country pack says which certificates count: insurance and license in the US, the construction tax exemption, social security and employers' liability clearances in Germany, where no waiver is asked for.",
      whyKey: "cases.roll_subcontractor_pay_applications_into_your_pay_application.step.require.why",
      whyDefault:
        "With the switch on, a missing waiver stops your own claim from being submitted, because you would be billing the owner for money you cannot release to the sub. A certificate that has lapsed by the period end stops it too, in every country.",
      moduleLabel: "Subcontractor Directory",
      moduleLabelKey: "nav.subcontractors",
      to: "/projects/:projectId/subcontractors",
    },
    {
      id: "waiver",
      icon: "FileSignature",
      inputs: [
        { labelKey: "cases.roll_subcontractor_pay_applications_into_your_pay_application.step.waiver.in.signed", label: "Signed conditional lien waiver" },
        { labelKey: "cases.roll_subcontractor_pay_applications_into_your_pay_application.step.waiver.in.application", label: "Sub's pay application for the month" },
      ],
      outputs: [
        { labelKey: "cases.roll_subcontractor_pay_applications_into_your_pay_application.step.waiver.out.filed", label: "Waiver on file for the pay application" },
        { labelKey: "cases.roll_subcontractor_pay_applications_into_your_pay_application.step.waiver.out.through", label: "Work released through the period end" },
      ],
      titleKey: "cases.roll_subcontractor_pay_applications_into_your_pay_application.step.waiver.title",
      titleDefault: "File the conditional waiver through the period end",
      whatKey: "cases.roll_subcontractor_pay_applications_into_your_pay_application.step.waiver.what",
      whatDefault:
        "On the subcontractor, under Lien waivers & tax forms, choose the conditional partial waiver type and pick the month's application in Pay application. That fills Waiver amount with its net and Releases work through with its period end; check both against the signed paper and upload it. Once the sub has been paid, file the unconditional waiver for the same period the same way.",
      whyKey: "cases.roll_subcontractor_pay_applications_into_your_pay_application.step.waiver.why",
      whyDefault:
        "A waiver that stops short of the period end leaves the last days of work open to a lien, and a lender's inspector reads that date first. Payment approval waits for a waiver that covers the net, and next month's claim checks that the unconditional one arrived.",
      moduleLabel: "Subcontractor Directory",
      moduleLabelKey: "nav.subcontractors",
      to: "/projects/:projectId/subcontractors",
    },
    {
      id: "approve",
      icon: "UserCheck",
      inputs: [
        { labelKey: "cases.roll_subcontractor_pay_applications_into_your_pay_application.step.approve.in.application", label: "Sub's pay application for the month" },
        { labelKey: "cases.roll_subcontractor_pay_applications_into_your_pay_application.step.approve.in.progress", label: "Work actually built" },
      ],
      outputs: [
        { labelKey: "cases.roll_subcontractor_pay_applications_into_your_pay_application.step.approve.out.approved", label: "Approved pay application" },
        { labelKey: "cases.roll_subcontractor_pay_applications_into_your_pay_application.step.approve.out.net", label: "Net amount for the period" },
      ],
      titleKey: "cases.roll_subcontractor_pay_applications_into_your_pay_application.step.approve.title",
      titleDefault: "Approve the subs' pay applications for the month",
      whatKey: "cases.roll_subcontractor_pay_applications_into_your_pay_application.step.approve.what",
      whatDefault:
        "On the Payments tab of each subcontractor, pick the agreement and check what the month's application claims against what was actually built on its work packages. Click Approve work for the site sign-off, or Reject with a reason. Then click Approve payment: the dialog lists each work package with Claimed and Approved, and you lower Approved on any line where less was done; it cannot go above the claim. Approve payment stays disabled until a waiver covering the net is on file where the agreement requires one.",
      whyKey: "cases.roll_subcontractor_pay_applications_into_your_pay_application.step.approve.why",
      whyDefault:
        "Your bill to the owner should never run ahead of what you have agreed to pay down the chain. The rollup carries the approved amounts to your claim, not the claimed ones, and an application included before it is approved is flagged, so the owner is never billed for work nobody on your side has checked.",
      moduleLabel: "Subcontractor Directory",
      moduleLabelKey: "nav.subcontractors",
      to: "/projects/:projectId/subcontractors",
    },
    {
      id: "include",
      icon: "Combine",
      inputs: [
        { labelKey: "cases.roll_subcontractor_pay_applications_into_your_pay_application.step.include.in.claim", label: "Your progress claim for the period" },
        { labelKey: "cases.roll_subcontractor_pay_applications_into_your_pay_application.step.include.in.open", label: "Open pay applications" },
      ],
      outputs: [
        { labelKey: "cases.roll_subcontractor_pay_applications_into_your_pay_application.step.include.out.rollup", label: "Subs' billing per SOV line" },
        { labelKey: "cases.roll_subcontractor_pay_applications_into_your_pay_application.step.include.out.mapped", label: "Every sub line on a billable line" },
      ],
      titleKey: "cases.roll_subcontractor_pay_applications_into_your_pay_application.step.include.title",
      titleDefault: "Include the subs' applications in your claim",
      whatKey: "cases.roll_subcontractor_pay_applications_into_your_pay_application.step.include.what",
      whatDefault:
        "Open your progress claim for the period on the contract. In the Subcontractor billing panel below the line items, tick the entries under Open pay applications that this claim bills and click Include. Each SOV line now shows Scheduled, GC this period, Subs this period and Subs to date, with a chip per pay application for its approval, its waiver and its certificates. If anything appears under Lines not on the schedule of values, choose an SOV line for it there.",
      whyKey: "cases.roll_subcontractor_pay_applications_into_your_pay_application.step.include.why",
      whyDefault:
        "Seeing the subs' figure next to yours on every line is what catches a line billed above its scheduled value, or a sub's work that would otherwise vanish from the bill because it was never linked. Nothing is written to your claim yet.",
      moduleLabel: "Contracts",
      moduleLabelKey: "nav.contracts",
      to: "/projects/:projectId/contracts",
    },
    {
      id: "hold",
      icon: "ListChecks",
      inputs: [
        { labelKey: "cases.roll_subcontractor_pay_applications_into_your_pay_application.step.hold.in.chips", label: "Waiver and certificate chips" },
        { labelKey: "cases.roll_subcontractor_pay_applications_into_your_pay_application.step.hold.in.included", label: "Included pay applications" },
      ],
      outputs: [
        { labelKey: "cases.roll_subcontractor_pay_applications_into_your_pay_application.step.hold.out.lines", label: "Claim lines from the subs' approved amounts" },
        { labelKey: "cases.roll_subcontractor_pay_applications_into_your_pay_application.step.hold.out.held", label: "Held-back pay application" },
      ],
      titleKey: "cases.roll_subcontractor_pay_applications_into_your_pay_application.step.hold.title",
      titleDefault: "Hold back a sub without paperwork, then commit the lines",
      whatKey: "cases.roll_subcontractor_pay_applications_into_your_pay_application.step.hold.what",
      whatDefault:
        "Where a chip reads No waiver, Waiver short of net or Certificate lapsed, click Exclude on that pay application; include it again once the paperwork is in. Then click Use subs' approved amounts, read the claim lines it suggests, tick the ones to bill and click Commit lines. Only the ticked lines are written, and the rest of your claim stays as it is.",
      whyKey: "cases.roll_subcontractor_pay_applications_into_your_pay_application.step.hold.why",
      whyDefault:
        "A sub left in without its required paperwork blocks the submission of your whole claim, so holding that one back keeps the rest of the month moving. The suggested amounts are capped at each line's scheduled value and reach your claim only when you commit them, so a person always reads the figures the owner will see.",
      moduleLabel: "Contracts",
      moduleLabelKey: "nav.contracts",
      to: "/projects/:projectId/contracts",
    },
  ],
};

export default playbook;
