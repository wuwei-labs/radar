// Safe: the same raw read, but the handler proves which account it was handed
// before touching the bytes — the address is derived on the path that reads it,
// not in a sibling helper.
use anchor_lang::prelude::*;

declare_id!("Fg6PaFpoGXkYsidMpWTK6W2BeZ7FEfcYkg476zPFsLnS");

#[program]
pub mod unvalidated_manual_account_access {
    use super::*;

    pub fn read_counter(ctx: Context<ReadCounter>) -> Result<()> {
        let info = ctx.accounts.counter.to_account_info();

        // The account is pinned to this program's own derivation before any
        // byte of it is read.
        let (expected, _bump) =
            Pubkey::find_program_address(&[b"counter", ctx.accounts.state.key().as_ref()], &crate::ID);
        require_keys_eq!(info.key(), expected);

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
    /// CHECK: derived and compared in the handler before its data is read
    pub counter: UncheckedAccount<'info>,
    pub authority: Signer<'info>,
}

#[account]
pub struct ProgramState {
    pub last_seen: u64,
}
