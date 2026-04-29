"use client";

import { useState } from "react";
import { Eye, EyeOff } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PasswordRules, isPasswordValid } from "@/components/shared/password-rules";
import { toast } from "sonner";
import { api } from "@/lib/api";

export function ChangePasswordForm() {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [showCurrent, setShowCurrent] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);

  const passwordsMatch = newPassword === confirmPassword;
  const isValid =
    currentPassword.trim().length > 0 &&
    isPasswordValid(newPassword) &&
    passwordsMatch;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!isValid || loading) return;

    if (!passwordsMatch) {
      toast.error("New passwords do not match.");
      return;
    }

    setLoading(true);
    try {
      await api.post("/api/v1/auth/change-password", {
        current_password: currentPassword,
        new_password: newPassword,
      });
      toast.success("Password updated successfully.");
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Failed to change password.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="bg-card rounded-xl border border-border p-6 max-w-md">
      <h3 className="text-sm font-semibold text-foreground mb-4">Change Password</h3>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="block text-sm font-medium text-foreground mb-1.5">
            Current password
          </label>
          <div className="relative">
            <Input
              type={showCurrent ? "text" : "password"}
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              placeholder="Enter current password"
              disabled={loading}
              required
              className="pr-10"
            />
            <button
              type="button"
              onClick={() => setShowCurrent((v) => !v)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-muted-foreground transition-colors"
              tabIndex={-1}
              aria-label={showCurrent ? "Hide password" : "Show password"}
            >
              {showCurrent ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
            </button>
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-foreground mb-1.5">
            New password
          </label>
          <div className="relative">
            <Input
              id="new-password"
              type={showNew ? "text" : "password"}
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              placeholder="At least 8 characters"
              disabled={loading}
              required
              minLength={8}
              className="pr-10"
              aria-describedby="password-rules"
            />
            <button
              type="button"
              onClick={() => setShowNew((v) => !v)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-muted-foreground transition-colors"
              tabIndex={-1}
              aria-label={showNew ? "Hide password" : "Show password"}
            >
              {showNew ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
            </button>
          </div>
          <PasswordRules value={newPassword} id="password-rules" />
        </div>

        <div>
          <label className="block text-sm font-medium text-foreground mb-1.5">
            Confirm new password
          </label>
          <div className="relative">
            <Input
              type={showConfirm ? "text" : "password"}
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              placeholder="Re-enter new password"
              disabled={loading}
              required
              className={`pr-10 ${
                confirmPassword && !passwordsMatch
                  ? "border-red-300 focus-visible:ring-red-300"
                  : ""
              }`}
            />
            <button
              type="button"
              onClick={() => setShowConfirm((v) => !v)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-muted-foreground transition-colors"
              tabIndex={-1}
              aria-label={showConfirm ? "Hide password" : "Show password"}
            >
              {showConfirm ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
            </button>
          </div>
          {confirmPassword && !passwordsMatch && (
            <p className="text-xs text-red-500 mt-1">Passwords do not match.</p>
          )}
        </div>

        <Button
          type="submit"
          className="bg-brand-500 hover:bg-brand-600 text-white w-full"
          disabled={loading || !isValid}
        >
          {loading ? "Updating..." : "Update Password"}
        </Button>
      </form>
    </div>
  );
}
