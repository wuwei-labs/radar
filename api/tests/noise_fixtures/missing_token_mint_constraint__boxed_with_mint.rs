// Safe pattern - a boxed token account that carries `token::mint`.
//
// The constraint is present, so "Missing Token Mint Constraint" must stay
// silent. Boxing is orthogonal to whether the mint is pinned.
//
// It did not stay silent. The rule walked a fixed three `.parent` hops from the
// `TokenAccount` node to reach the struct, and `Box<Account<'info,
// TokenAccount>>` nests one level deeper than the bare form, so the hop landed
// on the field instead. Its `derive(Accounts)` lookup then found nothing and
// raised - and because this rule's `except` block is its reporting path, the
// raise *was* the report. Every boxed token account in the codebase was flagged
// regardless of its constraints.
use anchor_lang::prelude::*;
use anchor_spl::token::{Mint, Token, TokenAccount};

declare_id!("Fg6PaFpoGXkYsidMpWTK6W2BeZ7FEfcYkg476zPFsLnS");

#[program]
pub mod boxed_with_mint {
    use super::*;

    pub fn deposit(ctx: Context<Deposit>, amount: u64) -> Result<()> {
        ctx.accounts.pool.total = ctx.accounts.pool.total + amount;
        Ok(())
    }
}

#[derive(Accounts)]
pub struct Deposit<'info> {
    #[account(mut)]
    pub pool: Box<Account<'info, Pool>>,
    #[account(mut, token::mint = mint)]
    pub user_token: Box<Account<'info, TokenAccount>>,
    #[account(mut, token::mint = mint)]
    pub maybe_fee_token: Option<Box<Account<'info, TokenAccount>>>,
    pub mint: Box<Account<'info, Mint>>,
    pub authority: Signer<'info>,
    pub token_program: Program<'info, Token>,
}

#[account]
pub struct Pool {
    pub total: u64,
}
