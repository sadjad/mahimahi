/* -*-mode:c++; tab-width: 4; indent-tabs-mode: nil; c-basic-offset: 4 -*- */

#include <limits>
#include <cassert>
#include <sys/types.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <sys/mman.h>
#include <unistd.h>

#include "link_queue.hh"
#include "timestamp.hh"
#include "util.hh"
#include "ezio.hh"
#include "abstract_packet_queue.hh"

using namespace std;

LinkQueue::LinkQueue( const string & link_name, const string & filename,
                      const string & logfile,
                      const bool graph_throughput, const bool graph_delay,
                      unique_ptr<AbstractPacketQueue> && packet_queue,
                      const string & command_line )
    : fd_( 0 ),
      control_file_( nullptr, [](uint64_t *p) { if (p) munmap(p, sizeof(uint64_t)); } ),
      base_timestamp_( timestamp() ),
      packet_queue_( move( packet_queue ) ),
      packet_in_transit_( "", 0 ),
      packet_in_transit_bytes_left_( 0 ),
      output_queue_(),
      log_(),
      throughput_graph_( nullptr ),
      delay_graph_( nullptr ),
      finished_( false )
{
    assert_not_root();

    fd_ = open( filename.c_str(), O_RDONLY );
    if ( fd_ == -1 ) {
    	  throw runtime_error( "Error opening file for reading" );
    }

    void *pps = mmap( 0, 2 * sizeof(uint64_t), PROT_READ, MAP_SHARED, fd_, 0 );
    if ( pps == MAP_FAILED ) {
        close( fd_ );
        throw runtime_error( "Error mmapping the file" );
    }
    control_file_.reset( (uint64_t *) pps );

    /* open logfile if called for */
    if ( not logfile.empty() ) {
        log_.reset( new ofstream( logfile ) );
        if ( not log_->good() ) {
            throw runtime_error( logfile + ": error opening for writing" );
        }

        *log_ << "# mahimahi mm-link (" << link_name << ") [" << filename << "] > " << logfile << endl;
        *log_ << "# command line: " << command_line << endl;
        *log_ << "# queue: " << packet_queue_->to_string() << endl;
        *log_ << "# init timestamp: " << initial_timestamp() << endl;
        *log_ << "# base timestamp: " << base_timestamp_ << endl;
        const char * prefix = getenv( "MAHIMAHI_SHELL_PREFIX" );
        if ( prefix ) {
            *log_ << "# mahimahi config: " << prefix << endl;
        }
    }

    /* create graphs if called for */
    if ( graph_throughput ) {
        throughput_graph_.reset( new BinnedLiveGraph( link_name + " [" + filename + "]",
                                                      { make_tuple( 1.0, 0.0, 0.0, 0.25, true ),
                                                        make_tuple( 0.0, 0.0, 0.4, 1.0, false ),
                                                        make_tuple( 1.0, 0.0, 0.0, 0.5, false ) },
                                                      "throughput (Mbps)",
                                                      8.0 / 1000000.0,
                                                      true,
                                                      500,
                                                      [] ( int, int & x ) { x = 0; } ) );
    }

    if ( graph_delay ) {
        delay_graph_.reset( new BinnedLiveGraph( link_name + " delay [" + filename + "]",
                                                 { make_tuple( 0.0, 0.25, 0.0, 1.0, false ) },
                                                 "queueing delay (ms)",
                                                 1, false, 250,
                                                 [] ( int, int & x ) { x = -1; } ) );
    }
}

void LinkQueue::record_arrival( const uint64_t arrival_time, const size_t pkt_size )
{
    /* log it */
    if ( log_ ) {
        *log_ << arrival_time << " + " << pkt_size << endl;
    }

    /* meter it */
    if ( throughput_graph_ ) {
        throughput_graph_->add_value_now( 1, pkt_size );
    }
}

void LinkQueue::record_departure_opportunity( void )
{
    /* log the delivery opportunity */
    if ( log_ ) {
        *log_ << next_delivery_time() << " # " << PACKET_SIZE << endl;
    }

    /* meter the delivery opportunity */
    if ( throughput_graph_ ) {
        throughput_graph_->add_value_now( 0, PACKET_SIZE );
    }
}

void LinkQueue::record_departure( const uint64_t departure_time, const QueuedPacket & packet )
{
    /* log the delivery */
    if ( log_ ) {
        *log_ << departure_time << " - " << packet.contents.size()
              << " " << departure_time - packet.arrival_time << endl;
    }

    /* meter the delivery */
    if ( throughput_graph_ ) {
        throughput_graph_->add_value_now( 2, packet.contents.size() );
    }

    if ( delay_graph_ ) {
        delay_graph_->set_max_value_now( 0, departure_time - packet.arrival_time );
    }
}

void LinkQueue::read_packet( const string & contents )
{
    const uint64_t now = timestamp();

    if ( contents.size() > PACKET_SIZE ) {
        throw runtime_error( "packet size is greater than maximum" );
    }

    rationalize( now );

    record_arrival( now, contents.size());

    uint64_t link_on = control_file_[1];
    if ( link_on == 1 ) {
        packet_queue_->enqueue( QueuedPacket( contents, now ) );
    }
}

uint64_t LinkQueue::next_delivery_time( void ) const
{
    if ( finished_ ) {
        return -1;
    } else {
        /* FIXME: this approach will have problems if the interval is
         * <1ms, such as when the rate exceeds 12Mbps_. */
        const uint64_t now = timestamp();
        const uint64_t interval = control_file_[0];
        if ( interval == 0 ) {
            throw runtime_error( "scheduling interval cannot be 0" );
        }
        const uint64_t scheduled_time = interval + base_timestamp_;
        return ( scheduled_time > now ) ? scheduled_time : now;
    }
}

void LinkQueue::use_a_delivery_opportunity( uint64_t delivery_time )
{
    record_departure_opportunity();

    base_timestamp_ = delivery_time;
}

/* emulate the link up to the given timestamp */
/* this function should be called before enqueueing any packets and before
   calculating the wait_time until the next event */
void LinkQueue::rationalize( const uint64_t now )
{
    while ( next_delivery_time() <= now ) {
        const uint64_t this_delivery_time = next_delivery_time();

        /* burn a delivery opportunity */
        unsigned int bytes_left_in_this_delivery = PACKET_SIZE;
        use_a_delivery_opportunity(this_delivery_time);

        while ( bytes_left_in_this_delivery > 0 ) {
            if ( not packet_in_transit_bytes_left_ ) {
                if ( packet_queue_->empty() ) {
                    break;
                }
                packet_in_transit_ = packet_queue_->dequeue();
                packet_in_transit_bytes_left_ = packet_in_transit_.contents.size();
            }

            assert( packet_in_transit_.arrival_time <= this_delivery_time );
            assert( packet_in_transit_bytes_left_ <= PACKET_SIZE );
            assert( packet_in_transit_bytes_left_ > 0 );
            assert( packet_in_transit_bytes_left_ <= packet_in_transit_.contents.size() );

            /* how many bytes of the delivery opportunity can we use? */
            const unsigned int amount_to_send = min( bytes_left_in_this_delivery,
                                                     packet_in_transit_bytes_left_ );

            /* send that many bytes */
            packet_in_transit_bytes_left_ -= amount_to_send;
            bytes_left_in_this_delivery -= amount_to_send;

            /* has the packet been fully sent? */
            if ( packet_in_transit_bytes_left_ == 0 ) {
                record_departure( this_delivery_time, packet_in_transit_ );

                /* this packet is ready to go */
                output_queue_.push( move( packet_in_transit_.contents ) );
            }
        }
    }
}

void LinkQueue::write_packets( FileDescriptor & fd )
{
    while ( not output_queue_.empty() ) {
        fd.write( output_queue_.front() );
        output_queue_.pop();
    }
}

unsigned int LinkQueue::wait_time( void )
{
    const auto now = timestamp();

    rationalize( now );

    if ( next_delivery_time() <= now ) {
        return 0;
    } else {
        return next_delivery_time() - now;
    }
}

bool LinkQueue::pending_output( void ) const
{
    return not output_queue_.empty();
}
