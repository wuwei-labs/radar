use anchor_lang::prelude::*;

use crate::state::Data;

#[derive(Accounts)]
pub struct Initialize<'info> {
    // VULN: `init_if_needed` hands the handler an account that may already
    // exist, and nothing in this program refuses the second call.
    #[account(init_if_needed, payer = user, space = 16)]
    pub data: Account<'info, Data>,
    #[account(mut)]
    pub user: Signer<'info>,
    pub system_program: Program<'info, System>,
}

pub fn handler(ctx: Context<Initialize>, value: u64) -> Result<()> {
    ctx.accounts.data.init(value)
}
