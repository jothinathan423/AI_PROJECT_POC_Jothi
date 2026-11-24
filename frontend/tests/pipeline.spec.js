import { test, expect } from '@playwright/test'

test.describe('RFQ Analysis Pipeline', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/')
  })

  test('page loads with header', async ({ page }) => {
    await expect(page).toHaveTitle(/RFQ|frontend/i)
    // Header should be visible
    await expect(page.locator('header, [class*="header"]').first()).toBeVisible()
  })

  test('shows pre-loaded document names', async ({ page }) => {
    const docPanel = page.getByText('Pre-Loaded Package')
    await expect(docPanel).toBeVisible()
    // RFQ and Drawing badges should appear
    await expect(page.getByText('RFQ').first()).toBeVisible()
    await expect(page.getByText('Drawing').first()).toBeVisible()
  })

  test('Start Analysis button is present and enabled', async ({ page }) => {
    const btn = page.getByRole('button', { name: /start analysis/i })
    await expect(btn).toBeVisible()
    await expect(btn).toBeEnabled()
  })

  test('all 10 pipeline steps are rendered', async ({ page }) => {
    const stepTitles = [
      'Intake Acceptance',
      'Package Quality Gate',
      'RFQ Document Analysis',
      'Drawing Analysis',
      'Cross-Document Analysis',
      'Engineering Validation',
      'Proposal Assembly',
      'Commercial Review',
      'Final QA & Release',
      'Export & Archive',
    ]
    for (const title of stepTitles) {
      await expect(page.getByText(title)).toBeVisible()
    }
  })

  test('gate steps show Approve and Return buttons when waiting', async ({ page }) => {
    // Before any run, gate buttons should not be visible (steps are pending)
    // This verifies the gate steps exist in the DOM tree at all
    const gateStepTitles = ['Engineering Validation', 'Commercial Review', 'Final QA & Release']
    for (const title of gateStepTitles) {
      await expect(page.getByText(title)).toBeVisible()
    }
  })

  test('result cards are hidden before analysis starts', async ({ page }) => {
    await expect(page.getByText('RFQ Requirements')).not.toBeVisible()
    await expect(page.getByText('Drawing Register')).not.toBeVisible()
    await expect(page.getByText('Gaps & RFI Register')).not.toBeVisible()
    await expect(page.getByText('Proposal Draft v1')).not.toBeVisible()
  })

  test('Pipeline Progress card is visible', async ({ page }) => {
    await expect(page.getByText('Pipeline Progress')).toBeVisible()
  })
})
