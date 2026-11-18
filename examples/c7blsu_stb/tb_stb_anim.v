`timescale 1ns/1ps
//
// Scenario for the c7blsu_stb animation. Inputs change at the falling edge;
// one line per cycle is printed 1 ns later, so it shows the registered
// state of the cycle (q), its inputs and the combinational decisions.
//
// BIU model: ack in the 2nd cycle the request is high, B response 2 cycles
// after the ack; PA 0x2000-0x3fff answers with an error.
//
module tb;

reg clk = 0, resetn = 0;
always #5 clk = ~clk;

reg         push = 0;
reg  [31:0] paddr = 0, vaddr = 0;
reg  [63:0] data = 0;
reg  [7:0]  strb = 0;
reg         so = 0;
reg  [31:0] ld_paddr = 0;
reg  [7:0]  ld_mask = 0;
reg         ld_vld = 0;
reg         err_clr = 0;
reg         ack = 0, fin = 0, fault = 0;

wire        full, empty, ld_hit, ld_fwd, so_done, so_fault, err, err_ovf;
wire [63:0] ld_data;
wire [31:0] err_vaddr, wr_addr;
wire [63:0] wr_data;
wire [7:0]  wr_strb;
wire        wr_req;

c7blsu_stb #(.DEPTH(4)) dut (
   .clk(clk), .resetn(resetn),
   .lsu_stb_push_ls2(push), .lsu_stb_paddr_ls2(paddr), .lsu_stb_vaddr_ls2(vaddr),
   .lsu_stb_data_ls2(data), .lsu_stb_strb_ls2(strb), .lsu_stb_so_ls2(so),
   .stb_lsu_full(full), .stb_lsu_empty(empty),
   .lsu_stb_ld_paddr_ls2(ld_paddr), .lsu_stb_ld_mask_ls2(ld_mask),
   .stb_lsu_ld_hit_ls2(ld_hit), .stb_lsu_ld_fwd_ls2(ld_fwd), .stb_lsu_ld_data_ls2(ld_data),
   .stb_lsu_so_done(so_done), .stb_lsu_so_fault(so_fault),
   .stb_lsu_err(err), .stb_lsu_err_ovf(err_ovf), .stb_lsu_err_vaddr(err_vaddr),
   .lsu_stb_err_clr(err_clr),
   .stb_biu_wr_req(wr_req), .stb_biu_wr_addr(wr_addr), .stb_biu_wr_data(wr_data),
   .stb_biu_wr_strb(wr_strb),
   .biu_stb_wr_ack(ack), .biu_stb_wr_fin(fin), .biu_stb_wr_fault(fault));

// ---- BIU model ----
integer req_cycles = 0;
integer b_wait = -1;
reg     b_err = 0;
always @(negedge clk) begin
   ack <= 0; fin <= 0; fault <= 0;
   if (resetn) begin
      if (wr_req) begin
         req_cycles = req_cycles + 1;
         if (req_cycles == 2) begin
            ack   <= 1;
            b_err  = (wr_addr >= 32'h2000 && wr_addr < 32'h4000);
            b_wait = 2;
            req_cycles = 0;
         end
      end else
         req_cycles = 0;
      if (b_wait == 0) begin
         if (b_err) fault <= 1; else fin <= 1;
         b_wait = -1;
      end else if (b_wait > 0)
         b_wait = b_wait - 1;
   end
end

// ---- scripted LSU side ----
integer cyc = 0;
task st;  // store of a word or byte, data already in its bus lane
   input [31:0] a; input [63:0] d; input [7:0] s; input o;
   begin push <= 1; paddr <= a; vaddr <= a | 32'h4000_0000; data <= d; strb <= s; so <= o; end
endtask
task ld;
   input [31:0] a; input [7:0] m;
   begin ld_vld <= 1; ld_paddr <= a; ld_mask <= m; end
endtask

always @(negedge clk) begin
   push <= 0; ld_vld <= 0; ld_mask <= 0; err_clr <= 0;
   if (resetn) begin
      cyc = cyc + 1;
      case (cyc)
         1:  st(32'h1000, 64'h00000000_AAAAAAAA, 8'h0F, 0);   // A: st.w 0x1000
         2:  st(32'h1004, 64'h000000BB_00000000, 8'h10, 0);   // B: st.b 0x1004
         3:  st(32'h2000, 64'h00000000_CCCCCCCC, 8'h0F, 0);   // C: st.w 0x2000 (will fail)
         4:  ld(32'h1000, 8'h0F);                             // ld.w 0x1000: forward from A
         5:  begin st(32'h1010, 64'h00000000_DDDDDDDD, 8'h0F, 0);   // D
                   ld(32'h1004, 8'hF0); end                   // ld.w 0x1004: partial hit on B
         6:  ld(32'h1004, 8'hF0);                             // still waiting (STB full)
         8:  st(32'h2004, 64'hEEEEEEEE_00000000, 8'hF0, 0);   // E: st.w 0x2004 (will fail)
         10: ld(32'h1004, 8'hF0);                             // still waiting for B
         12: begin st(32'h3000, 64'h00000000_FFFFFFFF, 8'h0F, 1);   // F: SO store (will fail)
                   ld(32'h1004, 8'hF0); end                   // B gone: miss, read memory
         21: st(32'h1020, 64'h00000000_99999999, 8'h0F, 0);   // G: push in the pop cycle
         28: err_clr <= 1;                                    // software clears STBERR
      endcase
   end
end

// ---- trace ----
integer k;
always @(negedge clk) begin
   #1;
   if (resetn && cyc >= 0 && cyc <= 38) begin
      $write("CYC %0d", cyc);
      $write(" push=%0d paddr=%h vaddr=%h data=%h strb=%h so=%0d", push, paddr, vaddr, data, strb, so);
      $write(" ld=%0d ldpa=%h ldmask=%h", ld_vld, ld_paddr, ld_mask);
      $write(" ack=%0d fin=%0d fault=%0d clr=%0d", ack, fin, fault, err_clr);
      $write(" v=%b iss=%0d req=%0d", dut.v_q, dut.iss_q, dut.biu_wr_req_q);
      $write(" issue=%0d pop=%0d shift=%0d slot=%b", dut.issue_start, dut.pop, dut.shift, dut.wr_slot);
      $write(" hit=%b cover=%b young=%b ldhit=%0d ldfwd=%0d lddata=%h", dut.hit, dut.cover, dut.youngest, ld_hit, ld_fwd, ld_data);
      $write(" full=%0d empty=%0d sodone=%0d sofault=%0d err=%0d ovf=%0d errva=%h errset=%0d",
             full, empty, so_done, so_fault, err, err_ovf, err_vaddr, dut.err_set);
      $write(" wraddr=%h wrdata=%h wrstrb=%h", wr_addr, wr_data, wr_strb);
      for (k = 0; k < 4; k = k + 1)
         $write(" e%0d=%h,%h,%h,%h,%0d", k, dut.paddr_q[k*32 +: 32], dut.vaddr_q[k*32 +: 32],
                dut.data_q[k*64 +: 64], dut.strb_q[k*8 +: 8], dut.so_q[k]);
      $write("\n");
   end
   if (cyc > 38) $finish;
end

initial begin
   repeat (3) @(negedge clk);
   resetn = 1;
end

endmodule
