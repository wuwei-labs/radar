// Safe pattern - the unchecked deserialize in a *constructor*.
//
// This is Anchor's deliberate `try_from_unchecked`, used where the caller has
// already established what the account is (an init path, a zero-copy loader).
// It returns a freshly built value rather than refreshing one that already
// exists, and it appears unchanged in the patched source of the disclosure that
// `type_cosplay__unchecked_reload.rs` covers.
//
// Reporting it would fire on the fixed and the vulnerable file alike, which
// distinguishes nothing - the exact failure the reload fixture exists to catch.
use anchor_lang::prelude::*;

declare_id!("Fg6PaFpoGXkYsidMpWTK6W2BeZ7FEfcYkg476zPFsLnS");

pub struct Wrapper<T> {
    account: T,
}

impl<T: AccountSerialize + AccountDeserialize + Clone> Wrapper<T> {
    /// Builds a wrapper from an account whose type the caller has established.
    pub fn try_from_unchecked(info: &AccountInfo) -> Result<Self> {
        if info.owner == &System::id() && info.lamports() == 0 {
            return Err(ProgramError::UninitializedAccount.into());
        }
        let mut data: &[u8] = &info.try_borrow_data()?;
        Ok(Self {
            account: T::try_deserialize_unchecked(&mut data)?,
        })
    }
}
