use anchor_lang::prelude::*;

use crate::state::Data;

#[derive(Accounts)]
pub struct Initialize<'info> {
    #[account(init_if_needed, payer = user, space = 24)]
    pub data: Account<'info, Data>,
    #[account(mut)]
    pub user: Signer<'info>,
    pub system_program: Program<'info, System>,
}

pub fn handler(ctx: Context<Initialize>, value: u64) -> Result<()> {
    // No guard here, deliberately: the type guards itself. Nothing in this file
    // names the flag, so the guard is only visible across the two.
    ctx.accounts.data.init(value)
}
