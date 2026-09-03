use anchor_lang::prelude::*;
use anchor_spl::token::{Token, TokenAccount};

use crate::state::{Vault, VAULT_SEED};

#[derive(Accounts)]
pub struct TransferTokens<'info> {
    #[account(mut)]
    pub from: Account<'info, TokenAccount>,
    #[account(mut)]
    pub to: Account<'info, TokenAccount>,
    // The seeds that `Vault::transfer_out` signs with, declared here: the vault
    // is derived per user, so its authority cannot stand in for another user's.
    #[account(
        seeds = [VAULT_SEED, user.key().as_ref()],
        bump = vault.bump,
        has_one = user,
    )]
    pub vault: Account<'info, Vault>,
    pub user: Signer<'info>,
    pub token_program: Program<'info, Token>,
}

pub fn handler(ctx: Context<TransferTokens>, amount: u64) -> Result<()> {
    ctx.accounts.vault.transfer_out(
        ctx.accounts.vault.to_account_info(),
        ctx.accounts.from.to_account_info(),
        ctx.accounts.to.to_account_info(),
        ctx.accounts.token_program.to_account_info(),
        amount,
    )
}
