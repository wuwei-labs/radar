// Vulnerable: the handler reads an UncheckedAccount's raw bytes without ever
// proving which account it was handed. Anchor validates nothing for
// UncheckedAccount, so a caller substitutes any account of the right shape and
// the handler happily reads it.
use anchor_lang::prelude::*;

declare_id!("Fg6PaFpoGXkYsidMpWTK6W2BeZ7FEfcYkg476zPFsLnS");

#[program]
pub mod unvalidated_manual_account_access {
    use super::*;

    pub fn read_counter(ctx: Context<ReadCounter>) -> Result<()> {
        // VULN: no derivation, no key comparison — nothing says this is the
        // counter belonging to this program.
        let info = ctx.accounts.counter.to_account_info();
        let data = info.try_borrow_data()?;
        let value = u64::from_le_bytes(data[0..8].try_into().unwrap());
        ctx.accounts.state.last_seen = value;
        Ok(())
    }
}

#[derive(Accounts)]
pub struct ReadCounter<'info> {
    #[account(mut)]
    pub state: Account<'info, ProgramState>,
    /// CHECK: read as raw bytes by the handler
    pub counter: UncheckedAccount<'info>,
    pub authority: Signer<'info>,
}

#[account]
pub struct ProgramState {
    pub last_seen: u64,
}
