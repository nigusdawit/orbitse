import { useState } from "react"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"
import { motion, AnimatePresence } from "framer-motion"
import { X, Calendar as CalendarIcon, Loader2 } from "lucide-react"
import { format } from "date-fns"
import { useCreateBooking } from "@/hooks/use-bookings"
import { galleryCards } from "@/lib/property-data"
import { useAuth } from "@/hooks/use-auth"
import { redirectToLogin } from "@/lib/auth-utils"
import { useToast } from "@/hooks/use-toast"

const bookingSchema = z.object({
  name: z.string().min(2, "Name required"),
  email: z.string().email("Invalid email"),
  roomId: z.string(),
  checkIn: z.string(),
  checkOut: z.string(),
  guests: z.coerce.number().min(1).max(8),
})

type BookingFormValues = z.infer<typeof bookingSchema>

interface BookingModalProps {
  isOpen: boolean
  onClose: () => void
  preselectedRoomId?: string
}

export function BookingModal({ isOpen, onClose, preselectedRoomId }: BookingModalProps) {
  const { user, isAuthenticated } = useAuth()
  const { mutate: createBooking, isPending } = useCreateBooking()
  const { toast } = useToast()
  
  const form = useForm<BookingFormValues>({
    resolver: zodResolver(bookingSchema),
    defaultValues: {
      roomId: preselectedRoomId || galleryCards[0].id,
      guests: 2,
      name: user?.firstName ? `${user.firstName} ${user.lastName || ''}`.trim() : "",
      email: user?.email || "",
    }
  })

  const onSubmit = (data: BookingFormValues) => {
    if (!isAuthenticated) {
      redirectToLogin(toast)
      return
    }

    // Calculate dummy price
    const totalPrice = 1200 * data.guests // Placeholder logic
    
    createBooking({
      ...data,
      userId: user!.id,
      totalPrice,
      status: "confirmed"
    }, {
      onSuccess: () => {
        onClose()
        form.reset()
      }
    })
  }

  const roomOptions = galleryCards.filter(c => c.category === 'rooms' || c.id === 'hero-villa')

  return (
    <AnimatePresence>
      {isOpen && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm">
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.95 }}
            className="w-full max-w-lg bg-background rounded-2xl shadow-2xl overflow-hidden"
          >
            <div className="p-6 border-b border-border/50 flex items-center justify-between">
              <div>
                <h2 className="text-2xl font-serif font-bold text-primary">Reserve Your Stay</h2>
                <p className="text-sm text-muted-foreground">Experience the serenity of Casa Serena</p>
              </div>
              <button onClick={onClose} className="p-2 hover:bg-muted rounded-full transition-colors">
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={form.handleSubmit(onSubmit)} className="p-6 space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Full Name</label>
                  <input
                    {...form.register("name")}
                    className="w-full px-3 py-2 rounded-lg border bg-secondary/20 focus:outline-none focus:ring-2 focus:ring-primary/20 transition-all"
                    placeholder="John Doe"
                  />
                  {form.formState.errors.name && <p className="text-xs text-destructive">{form.formState.errors.name.message}</p>}
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Email</label>
                  <input
                    {...form.register("email")}
                    className="w-full px-3 py-2 rounded-lg border bg-secondary/20 focus:outline-none focus:ring-2 focus:ring-primary/20 transition-all"
                    placeholder="john@example.com"
                  />
                  {form.formState.errors.email && <p className="text-xs text-destructive">{form.formState.errors.email.message}</p>}
                </div>
              </div>

              <div className="space-y-2">
                <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Select Room</label>
                <select
                  {...form.register("roomId")}
                  className="w-full px-3 py-2 rounded-lg border bg-secondary/20 focus:outline-none focus:ring-2 focus:ring-primary/20 transition-all"
                >
                  {roomOptions.map(room => (
                    <option key={room.id} value={room.id}>{room.title} - {room.price}</option>
                  ))}
                </select>
              </div>

              <div className="grid grid-cols-3 gap-4">
                <div className="space-y-2">
                  <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Check In</label>
                  <input
                    type="date"
                    {...form.register("checkIn")}
                    className="w-full px-3 py-2 rounded-lg border bg-secondary/20 focus:outline-none focus:ring-2 focus:ring-primary/20 transition-all"
                  />
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Check Out</label>
                  <input
                    type="date"
                    {...form.register("checkOut")}
                    className="w-full px-3 py-2 rounded-lg border bg-secondary/20 focus:outline-none focus:ring-2 focus:ring-primary/20 transition-all"
                  />
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Guests</label>
                  <input
                    type="number"
                    min="1"
                    max="8"
                    {...form.register("guests")}
                    className="w-full px-3 py-2 rounded-lg border bg-secondary/20 focus:outline-none focus:ring-2 focus:ring-primary/20 transition-all"
                  />
                </div>
              </div>

              <div className="pt-4 flex justify-end gap-3">
                <button
                  type="button"
                  onClick={onClose}
                  className="px-4 py-2 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isPending}
                  className="px-6 py-2 bg-primary text-primary-foreground font-serif font-medium rounded-lg hover:bg-primary/90 transition-all disabled:opacity-50 flex items-center gap-2"
                >
                  {isPending && <Loader2 className="w-4 h-4 animate-spin" />}
                  {isAuthenticated ? "Confirm Reservation" : "Login to Reserve"}
                </button>
              </div>
            </form>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  )
}
