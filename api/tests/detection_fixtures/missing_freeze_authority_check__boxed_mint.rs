// Real bug, boxed - the recall side of the same wrapper problem.
//
// The program takes a deposit against a mint it never checks the
// freeze_authority of, so the issuer can freeze the token accounts and trap the
// funds. "Missing Freeze Authority Check" must report it.
//
// It did not. The rule reached its struct by three fixed `.parent` hops, and
// `Box<Account<'info, Mint>>` nests one deeper, so the hop landed on the field;
// the `derive(Accounts)` lookup found nothing, raised, and this rule's `except`
// is a bare `continue`. So unlike the token-mint rule - where the same hop bug
// caused false positives - here it silently dropped the finding. The wrapper a
// program happens to use decided whether the rule ran at all.
use anchor_lang::prelude::*;
use anchor_spl::token::{self, Mint, Token, TokenAccount};

declare_id!("Fg6PaFpoGXkYsidMpWTK6W2BeZ7FEfcYkg476zPFsLnS");

#[program]
pub mod boxed_mint_unchecked {
    use super::*;

    pub fn deposit(ctx: Context<Deposit>, amount: u64) -> Result<()> {
        // VULN: the mint's freeze_authority is never inspected before taking
        // custody of the caller's tokens.
        let accounts = token::Transfer {
            from: ctx.accounts.user_token.to_account_info(),
            to: ctx.accounts.vault_token.to_account_info(),
            authority: ctx.accounts.authority.to_account_info(),
        };
        let program = ctx.accounts.token_program.to_account_info();
        token::transfer(CpiContext::new(program, accounts), amount)
    }
}

#[derive(Accounts)]
pub struct Deposit<'info> {
    pub mint: Box<Account<'info, Mint>>,
    #[account(mut)]
    pub user_token: Box<Account<'info, TokenAccount>>,
    #[account(mut)]
    pub vault_token: Box<Account<'info, TokenAccount>>,
    pub authority: Signer<'info>,
    pub token_program: Program<'info, Token>,
}
