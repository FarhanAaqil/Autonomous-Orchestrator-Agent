import { test, expect } from '@playwright/test';

test('signup and forgot-password screens show neutral email guidance', async ({page}) => {
  await page.route('**/auth/options', route => route.fulfill({json: {registration: true}}));
  await page.route('**/auth/register', route => {
    expect(route.request().postDataJSON()).toEqual({email: 'new@example.com', password: 'fixture-password-123'});
    return route.fulfill({status: 202, json: {message: 'Check your email for a verification link.'}});
  });
  await page.route('**/auth/password/reset/request', route => route.fulfill({status: 202, json: {message: 'If this account exists, check your email.'}}));
  await page.goto('/');
  await page.getByRole('button', {name: 'Sign up', exact: true}).click();
  await page.getByLabel('Email', {exact: true}).fill('new@example.com');
  await page.getByLabel('Password', {exact: true}).fill('fixture-password-123');
  await page.getByRole('button', {name: 'Create account', exact: true}).click();
  await expect(page.getByRole('status')).toContainText('Check your email');
  await page.getByRole('button', {name: 'Back to sign in'}).click();
  await page.getByRole('button', {name: 'Forgot password?'}).click();
  await page.getByLabel('Email', {exact: true}).fill('new@example.com');
  await page.getByRole('button', {name: 'Send reset link'}).click();
  await expect(page.getByRole('status')).toContainText('If this account exists');
});

for (const action of ['verify', 'reset']) {
  test(`${action} uses explicit confirmation and removes the token from the address`, async ({page}) => {
    let submitted = false;
    await page.route(action === 'verify' ? '**/auth/verify' : '**/auth/password/reset/confirm', route => {
      submitted = true;
      expect(route.request().postDataJSON().token).toBe('fixture-token');
      return route.fulfill({json: {verified: true, changed: true}});
    });
    await page.goto('/#action=' + action + '&token=fixture-token');
    await expect(page.getByRole('heading', {name: action === 'verify' ? 'Confirm your email.' : 'Choose a new password.'})).toBeVisible();
    expect(page.url()).not.toContain('token=');
    expect(submitted).toBe(false);
    if (action === 'reset') await page.getByLabel('Password', {exact: true}).fill('replacement-password-123');
    await page.getByRole('button', {name: action === 'verify' ? 'Verify email' : 'Reset password', exact: true}).click();
    await expect(page.getByRole('heading', {name: 'Welcome back.'})).toBeVisible();
    expect(submitted).toBe(true);
  });
}
